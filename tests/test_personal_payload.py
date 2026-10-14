from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import pytest

from vault_unified import backup_manager, vault_format
from vault_unified.crypto import decrypt_payload, write_encrypted_file
from vault_unified.local_store import EntryTransactionConflict, LocalVault
from vault_unified.manager import UnifiedVault
from vault_unified.models import SecretEntry
from vault_unified.recovery_kit import create_recovery_kit, generate_recovery_code, restore_from_recovery_kit
from vault_unified.v3_crypto import (
    V3PayloadError, create_v3_container, create_v3_file, rotate_v3_password,
    update_v3_container,
)

PASSWORD = "generated-payload-test-password"


@pytest.fixture(autouse=True)
def isolated_backup_catalog(tmp_path, monkeypatch):
    monkeypatch.setattr(backup_manager, "backup_catalog_path", lambda: tmp_path / "catalog.json")
    monkeypatch.setattr(backup_manager, "default_backup_dir", lambda: tmp_path / "backups")


@pytest.mark.parametrize("framed", [False, True])
def test_upgrade_preserves_entries_and_retains_old_readable_backup(tmp_path: Path, framed: bool):
    path = tmp_path / "active.vault"
    payload = {"version": 2, "entries": {}}
    if framed:
        create_v3_file(path, PASSWORD, payload)
    else:
        write_encrypted_file(path, PASSWORD, payload)
    vault = LocalVault(path, PASSWORD)
    vault.add(SecretEntry(title="Generated", password="generated-only", source_metadata={"other": {"kept": True}}))
    old = path.read_bytes()
    before = vault.export_payload()
    backup = vault.upgrade_payload(expected_generation=vault.generation, expected_sha256=hashlib.sha256(old).hexdigest())
    assert Path(backup).read_bytes() == old
    assert next(item for item in backup_manager.list_backups(path, PASSWORD) if item.path == backup).pinned
    assert vault.export_payload() == {**before, "version": 3, "metadata": {}}
    assert LocalVault(path, PASSWORD).export_payload() == vault.export_payload()


def test_old_reader_rejects_new_payload_before_attempting_decryption(monkeypatch):
    frame = create_v3_container(PASSWORD, {"version": 3, "entries": {}, "metadata": {}})
    monkeypatch.setattr(vault_format, "SUPPORTED_PAYLOAD_SCHEMAS", frozenset({2}))
    with pytest.raises(vault_format.VaultFormatError, match="Unsupported payload schema"):
        decrypt_payload(PASSWORD, frame)


def test_payload_metadata_survives_edit_import_undo_password_change_and_recovery(tmp_path: Path):
    path = tmp_path / "active.vault"
    entry = SecretEntry(title="Generated", password="generated-value")
    metadata = {"generated_passwords": [{"value": "generated-history"}], "future_namespace": {"keep": [1, 2]}}
    initial = {"version": 3, "entries": {entry.id: entry.to_dict()}, "metadata": metadata}
    create_v3_file(path, PASSWORD, initial)
    vault = UnifiedVault(path, PASSWORD)
    edited = copy.deepcopy(vault.local.get(entry.id))
    edited.title = "Changed"
    vault.local.commit_entry(edited, create=False, expected_updated_at=entry.updated_at)
    assert decrypt_payload(PASSWORD, path.read_bytes())["metadata"] == metadata
    before = vault.local.export_payload()
    digest = vault.local.state_digest()
    vault.local.commit_import_batch([SecretEntry(title="Imported")], updated_entry_ids=set(), expected_generation=vault.local.generation, expected_digest=digest)
    vault.local.restore_import_payload(before, expected_generation=vault.local.generation, expected_digest=vault.local.state_digest(), restored_digest=digest)
    assert vault.local.export_payload() == before
    rotated = rotate_v3_password(PASSWORD, "generated-new-password", path.read_bytes())
    assert decrypt_payload("generated-new-password", rotated) == before
    code = generate_recovery_code()
    kit = create_recovery_kit(vault, code, tmp_path / "kit")
    target = tmp_path / "restored.vault"
    restore_from_recovery_kit(target, kit, code, PASSWORD)
    assert LocalVault(target, PASSWORD).export_payload() == before


def test_upgrade_stale_preview_and_backup_failure_do_not_change_vault(tmp_path: Path, monkeypatch):
    path = tmp_path / "active.vault"
    vault = LocalVault.create(path, PASSWORD)
    old = path.read_bytes()
    with pytest.raises(EntryTransactionConflict):
        vault.upgrade_payload(expected_generation=vault.generation, expected_sha256="0" * 64)
    def fail(*args, **kwargs):
        raise OSError("generated backup failure")
    monkeypatch.setattr(backup_manager, "create_manual_backup", fail)
    with pytest.raises(OSError, match="backup failure"):
        vault.upgrade_payload(expected_generation=vault.generation, expected_sha256=hashlib.sha256(old).hexdigest())
    assert path.read_bytes() == old
    assert vault.payload_version == 2


def test_schema_downgrade_and_legacy_schema_three_write_refused(tmp_path: Path):
    frame = create_v3_container(PASSWORD, {"version": 3, "entries": {}, "metadata": {"keep": True}})
    with pytest.raises(V3PayloadError, match="downgrade"):
        update_v3_container(PASSWORD, {"version": 2, "entries": {}}, frame)
    with pytest.raises(ValueError, match="framed"):
        write_encrypted_file(tmp_path / "legacy.vault", PASSWORD, {"version": 3, "entries": {}, "metadata": {}})


def test_upgrade_write_failure_keeps_old_memory_and_pinned_backup(tmp_path: Path, monkeypatch):
    from vault_unified import storage
    path = tmp_path / "active.vault"
    vault = LocalVault.create(path, PASSWORD)
    before = path.read_bytes()
    writer = storage.atomic_write_bytes
    def fail_active(target, *args, **kwargs):
        if target == path:
            raise OSError("generated replacement failure")
        return writer(target, *args, **kwargs)
    monkeypatch.setattr(storage, "atomic_write_bytes", fail_active)
    with pytest.raises(OSError, match="replacement failure"):
        vault.upgrade_payload(expected_generation=vault.generation, expected_sha256=hashlib.sha256(before).hexdigest())
    assert path.read_bytes() == before
    assert vault.payload_version == 2
    assert any(item.pinned and Path(item.path).read_bytes() == before for item in backup_manager.list_backups(path, PASSWORD))


def test_existing_device_slot_survives_schema_upgrade():
    import secrets
    from uuid import uuid4
    from vault_unified.v3_crypto import V3DeviceCredential, add_v3_device_slot
    credential = V3DeviceCredential(slot_id=str(uuid4()), key=secrets.token_bytes(32))
    frame = add_v3_device_slot(PASSWORD, credential, create_v3_container(PASSWORD, {"version": 2, "entries": {}}))
    upgraded = update_v3_container(credential, {"version": 3, "entries": {}, "metadata": {}}, frame)
    before, after = map(vault_format.parse_vault_container, (frame, upgraded))
    assert before.header.key_slots == after.header.key_slots
    assert decrypt_payload(credential, upgraded) == decrypt_payload(PASSWORD, upgraded)


def test_authenticated_header_must_match_payload_schema():
    from dataclasses import replace
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from vault_unified.v3_crypto import _unlock_dek, _payload_aad, _assemble_frame
    frame = create_v3_container(PASSWORD, {"version": 2, "entries": {}})
    container = vault_format.parse_vault_container(frame)
    dek = _unlock_dek(PASSWORD, container)
    plaintext = AESGCM(dek).decrypt(container.header.payload_nonce, container.ciphertext, _payload_aad(container.header))
    header = replace(container.header, payload_schema=3)
    mismatched = _assemble_frame(header, AESGCM(dek).encrypt(header.payload_nonce, plaintext, _payload_aad(header)))
    with pytest.raises(V3PayloadError, match="differs"):
        decrypt_payload(PASSWORD, mismatched)

from pathlib import Path
import base64
import secrets
from tempfile import TemporaryDirectory

import pytest

from test_system_session_lock import runtime
from vault_unified import recovery_rehearsal as rehearsal
from vault_unified.crypto import decrypt_payload
from vault_unified.organization import prepare_action
from vault_unified.personal_data import add_attachment, record_history, update_data
from vault_unified.recovery_kit import create_recovery_kit, generate_recovery_code
from vault_unified.session import sessions
from vault_unified.v3_crypto import create_v3_file


def package(auth, tmp_path):
    vault = sessions.get(auth["Authorization"].split()[1])
    entry = vault.add("Generated migration entry", "generated", secrets.token_hex(24), auto_push=False)
    update_data(entry, totp_secret="JBSWY3DPEHPK3PXP", custom_fields=[{"label": "generated", "value": secrets.token_hex(8), "concealed": True}])
    add_attachment(entry, filename="generated.txt", mime_type="text/plain", data_b64=base64.b64encode(b"generated attachment").decode())
    record_history(entry)
    vault.local.commit_entry(entry, create=False, expected_updated_at=entry.updated_at)
    archived = vault.add("Generated archive", "generated", secrets.token_hex(20), auto_push=False)
    vault.local.commit_entry(prepare_action(archived, "archive", tags=[]), create=False, expected_updated_at=archived.updated_at)
    trash = vault.add("Generated trash", "generated", secrets.token_hex(20), auto_push=False)
    vault.local.commit_entry(prepare_action(trash, "trash", tags=[]), create=False, expected_updated_at=trash.updated_at)
    vault.local.update_metadata("vault_unified:generated_test", lambda _: {"opaque": secrets.token_hex(32)})
    code = generate_recovery_code()
    kit = create_recovery_kit(vault, code, tmp_path / "kits")
    return vault, kit, code


def test_real_restore_reopen_and_all_payload_comparison_leave_source_and_session_unchanged(runtime, tmp_path, monkeypatch):
    _, client, headers, auth, _ = runtime
    vault, kit, code = package(auth, tmp_path)
    original, encrypted = vault.vault_path.read_bytes(), kit.read_bytes()
    temporary = []
    def isolated(**kwargs):
        item = TemporaryDirectory(dir=tmp_path, **kwargs)
        temporary.append(Path(item.name))
        return item
    monkeypatch.setattr(rehearsal, "TemporaryDirectory", isolated)
    response = client.post("/api/auth/recover/rehearse", headers=headers, json={"kit_path": str(kit), "recovery_code": code})
    assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
    assert response.json()["counts"] == {"entries": 3, "active": 1, "archived": 1, "trash": 1, "attachments": 1, "history": 2, "totp": 1}
    assert response.json()["complete_payload_matched"] and response.json()["temporary_copy_removed"]
    assert temporary and all(not path.exists() for path in temporary)
    assert vault.vault_path.read_bytes() == original and kit.read_bytes() == encrypted
    assert sessions.get(auth["Authorization"].split()[1]) is vault
    assert code not in response.text and "opaque" not in response.text
    assert client.post("/api/auth/recover/rehearse", json={"kit_path": str(kit), "recovery_code": code}).status_code == 403


def test_rehearsal_supports_schema_two_and_a_new_computer_without_vault(tmp_path):
    code = generate_recovery_code()
    kit = tmp_path / "old.vault"
    create_v3_file(kit, code, {"version": 2, "entries": {}})
    result = rehearsal.rehearse_recovery(kit, code)
    assert result["payload_version"] == 2 and result["counts"]["entries"] == 0
    assert {path.name for path in tmp_path.iterdir()} == {"old.vault"}


@pytest.mark.parametrize("failure", ["wrong-code", "damaged-file", "partial-write", "data-mismatch"])
def test_failed_rehearsal_never_touches_current_data_and_cleans_temporary_files(runtime, tmp_path, monkeypatch, failure):
    _, client, headers, auth, _ = runtime
    vault, kit, code = package(auth, tmp_path)
    original = vault.vault_path.read_bytes()
    directories = []
    def isolated(**kwargs):
        item = TemporaryDirectory(dir=tmp_path, **kwargs); directories.append(Path(item.name)); return item
    monkeypatch.setattr(rehearsal, "TemporaryDirectory", isolated)
    if failure == "wrong-code": code = generate_recovery_code()
    if failure == "damaged-file": kit.write_bytes(kit.read_bytes()[:-20])
    if failure == "partial-write":
        def fail(target, *args, **kwargs):
            target.write_bytes(b"generated incomplete ciphertext")
            raise OSError("generated private failure")
        monkeypatch.setattr(rehearsal, "restore_from_recovery_kit", fail)
    if failure == "data-mismatch":
        def discard(target, source, credential, password, **kwargs):
            payload = decrypt_payload(credential, source.read_bytes())
            payload["metadata"] = {}
            create_v3_file(target, password, payload)
        monkeypatch.setattr(rehearsal, "restore_from_recovery_kit", discard)
    response = client.post("/api/auth/recover/rehearse", headers=headers, json={"kit_path": str(kit), "recovery_code": code})
    assert response.status_code == 400
    assert code not in response.text and "generated private" not in response.text
    assert vault.vault_path.read_bytes() == original and all(not path.exists() for path in directories)


def test_invalid_recovery_requests_never_echo_credentials(runtime):
    _, client, headers, _, _ = runtime
    response = client.post("/api/auth/recover/rehearse", headers=headers, json={"kit_path": "generated.vault", "recovery_code": "generated-short-code"})
    assert response.status_code == 422 and "generated-short-code" not in response.text

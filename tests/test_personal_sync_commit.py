import copy
import secrets

import pytest

from vault_unified.local_store import LocalVault, EntryTransactionConflict
from vault_unified.models import SecretEntry
from vault_unified.v3_crypto import create_v3_file


def local(tmp_path):
    path, password = tmp_path / "generated.vault", secrets.token_hex(20)
    create_v3_file(path, password, {"version": 3, "entries": {}, "metadata": {}})
    return LocalVault(path, password)


def test_replication_state_and_entries_commit_together_and_reopen(tmp_path):
    vault = local(tmp_path)
    generation, payload = vault.sync_snapshot()
    entry = SecretEntry(title="Generated sync commit", password=secrets.token_hex(20))
    payload["entries"][entry.id] = entry.to_dict()
    payload["metadata"]["vault_unified:personal_sync"] = {"generated": "encrypted state"}
    vault.commit_sync_payload(payload, expected_generation=generation)
    assert LocalVault(vault.vault_path, vault.credential).export_payload() == payload
    assert entry.password.encode() not in vault.vault_path.read_bytes()


def test_edit_during_network_io_prevents_sync_overwrite(tmp_path):
    vault = local(tmp_path)
    generation, pending = vault.sync_snapshot()
    entry = vault.add(SecretEntry(title="Generated concurrent edit"))
    before = vault.vault_path.read_bytes()
    with pytest.raises(EntryTransactionConflict): vault.commit_sync_payload(pending, expected_generation=generation)
    assert vault.vault_path.read_bytes() == before and vault.get(entry.id)


def test_second_unlocked_instance_cannot_overwrite_newer_disk_data(tmp_path):
    a = local(tmp_path); b = LocalVault(a.vault_path, a.credential)
    entry = a.add(SecretEntry(title="Generated first session"))
    generation, payload = b.sync_snapshot()
    before = a.vault_path.read_bytes()
    with pytest.raises(EntryTransactionConflict, match="disk"):
        b.commit_sync_payload(payload, expected_generation=generation)
    with pytest.raises(EntryTransactionConflict, match="disk"):
        b.update_metadata("generated:stale", lambda _: "generated")
    assert a.vault_path.read_bytes() == before
    assert LocalVault(a.vault_path, a.credential).get(entry.id)


def test_failed_atomic_sync_keeps_live_memory_entries_and_outbox(tmp_path, monkeypatch):
    vault = local(tmp_path)
    generation, before = vault.sync_snapshot(); candidate = copy.deepcopy(before)
    candidate["metadata"]["vault_unified:personal_sync"] = {"outbox": "generated"}
    disk = vault.vault_path.read_bytes()
    def fail(*args, **kwargs): raise OSError("generated write failure")
    monkeypatch.setattr("vault_unified.local_store.write_encrypted_file", fail)
    with pytest.raises(OSError): vault.commit_sync_payload(candidate, expected_generation=generation)
    assert vault.export_payload() == before and vault.vault_path.read_bytes() == disk and vault.generation == generation

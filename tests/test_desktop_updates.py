from pathlib import Path

from test_system_session_lock import runtime
from vault_unified.backup_manager import list_backups
from vault_unified.crypto import decrypt_payload
from vault_unified.models import SecretEntry
from vault_unified.session import sessions


def test_update_backup_requires_native_and_explicit_consent(runtime):
    _, client, _, auth, _ = runtime
    local = sessions.get(auth["Authorization"].split()[1]).local
    original = local.vault_path.read_bytes()
    renderer = {k: v for k, v in auth.items() if k != "X-Vault-Native"}
    assert client.post("/api/personal/update/prepare", headers=renderer, json={"confirm": True}).status_code == 403
    for value in (False, "true", 1):
        assert client.post("/api/personal/update/prepare", headers=auth, json={"confirm": value}).status_code in (400, 422)
    assert local.vault_path.read_bytes() == original and not list_backups(local.vault_path, local.credential)


def test_verified_pinned_backup_preserves_full_payload_and_locks_all_sessions(runtime):
    _, client, headers, auth, master = runtime
    local = sessions.get(auth["Authorization"].split()[1]).local
    local.add(SecretEntry(title="Generated update account", notes="Generated notes"))
    local.update_metadata("vault_unified:generated-update", lambda _: {"complete": [1, 2, 3]})
    second = client.post("/api/auth/unlock", headers=headers, json={"password": master}).json()["token"]
    original = local.vault_path.read_bytes()
    response = client.post("/api/personal/update/prepare", headers=auth, json={"confirm": True})
    assert response.status_code == 200 and response.json()["locked"]
    assert Path(response.json()["backup_path"]).read_bytes() == original == local.vault_path.read_bytes()
    assert decrypt_payload(local.credential, original) == local.export_payload()
    assert not sessions.is_unlocked(second) and client.get("/api/entries", headers=auth).status_code == 401
    assert any(record.path == response.json()["backup_path"] and record.pinned and record.verified for record in list_backups(local.vault_path, local.credential))
    assert client.post("/api/auth/unlock", headers=headers, json={"password": master}).status_code == 200


def test_backup_failure_stops_update_without_locking_or_changing_data(runtime, monkeypatch):
    _, client, _, auth, _ = runtime
    local = sessions.get(auth["Authorization"].split()[1]).local; original = local.vault_path.read_bytes()
    def fail(*_args, **_kwargs): raise OSError("Generated full disk")
    monkeypatch.setattr("vault_unified.backup_manager.create_manual_backup", fail)
    assert client.post("/api/personal/update/prepare", headers=auth, json={"confirm": True}).status_code == 409
    assert client.get("/api/entries", headers=auth).status_code == 200 and local.vault_path.read_bytes() == original

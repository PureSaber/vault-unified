import copy
import secrets
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from pathlib import Path

import pytest

from vault_unified.personal_sync.connections import Connections, SERVICE
from vault_unified.personal_sync.codec import STATE_NAMESPACE, ProtocolError
from vault_unified.personal_sync.payload import project
from vault_unified.personal_sync.transport import StorageUnavailable
from vault_unified.local_store import LocalVault, EntryTransactionConflict
from vault_unified.models import SecretEntry
from vault_unified.v3_crypto import create_v3_file
from vault_unified.session import sessions
from test_system_session_lock import runtime


class GeneratedKeyring:
    def __init__(self): self.records = {}; self.fail_delete = False
    def get_password(self, service, account): return self.records.get((service, account))
    def set_password(self, service, account, value): self.records[service, account] = value
    def delete_password(self, service, account):
        if self.fail_delete: raise OSError("Generated cleanup failure")
        self.records.pop((service, account), None)


def profile(directory, backend):
    directory.mkdir()
    path, password = directory / "generated.vault", secrets.token_hex(20)
    create_v3_file(path, password, {"version": 3, "entries": {}, "metadata": {}})
    return LocalVault(path, password), Connections(config_dir=directory / "config", backend_factory=lambda: backend)


def options(directory, *, code=""):
    return {"provider": "folder", "mode": "join" if code else "create", "location": str(directory),
            "label": "Generated computer", "automatic": False, "username": "", "password": "", "code": code}


def connect(local, manager, directory, *, code=""):
    preview = manager.preview(local, "generated-session", options(directory, code=code))
    return manager.apply(local, "generated-session", preview["preview_token"])


def test_preview_cancel_replay_scope_and_stale_state_never_activate_connection(tmp_path):
    backend = GeneratedKeyring(); local, manager = profile(tmp_path / "a", backend)
    before = local.vault_path.read_bytes()
    preview = manager.preview(local, "generated-owner", options(tmp_path))
    assert local.vault_path.read_bytes() == before and not backend.records
    with pytest.raises(ProtocolError): manager.apply(local, "generated-other", preview["preview_token"])
    manager.cancel("generated-owner", preview["preview_token"])
    with pytest.raises(ProtocolError): manager.apply(local, "generated-owner", preview["preview_token"])
    assert local.vault_path.read_bytes() == before and not list(tmp_path.glob("VaultUnified-*"))
    preview = manager.preview(local, "generated-owner", options(tmp_path))
    local.add(SecretEntry(title="Generated newer edit")); edited = local.vault_path.read_bytes()
    with pytest.raises(EntryTransactionConflict): manager.apply(local, "generated-owner", preview["preview_token"])
    assert local.vault_path.read_bytes() == edited and not backend.records


def test_create_join_real_vault_preview_backup_and_restart_connection(tmp_path):
    backend = GeneratedKeyring()
    a, am = profile(tmp_path / "a", backend); b, bm = profile(tmp_path / "b", backend)
    entry = a.add(SecretEntry(title="Generated shared account", password=secrets.token_hex(20)))
    connect(a, am, tmp_path)
    code = am.code(a)
    assert len(backend.records) == 1 and all(key[0] == SERVICE for key in backend.records)
    assert code.encode() not in a.vault_path.read_bytes()
    assert am.synchronize(a, automatic=True) == {"skipped": True}
    am.synchronize(a)
    before = b.vault_path.read_bytes()
    preview = bm.preview(b, "generated-session", options(tmp_path, code=code))
    assert preview["total"] == 1 and preview["result_entries"] == 1 and b.vault_path.read_bytes() == before
    result = bm.apply(b, "generated-session", preview["preview_token"])
    assert Path(result["backup_path"]).is_file()
    assert b.get(entry.id).password == entry.password
    bm.synchronize(b); am.synchronize(a)
    reopened = LocalVault(b.vault_path, b.credential)
    next_manager = Connections(config_dir=tmp_path / "b/config", backend_factory=lambda: backend)
    assert next_manager.status(reopened)["connected"] and next_manager.code(reopened) == code
    assert project(a.export_payload()) == project(b.export_payload())
    assert len(am.status(a)["devices"]) == 2
    for file in (tmp_path / "a/config").iterdir():
        assert code not in file.read_text() and entry.password not in file.read_text()


def test_recovered_payload_does_not_reuse_previous_device_identity(tmp_path):
    backend = GeneratedKeyring(); a, am = profile(tmp_path / "a", backend)
    connect(a, am, tmp_path); am.synchronize(a)
    code, previous = am.code(a), a.metadata_value(STATE_NAMESPACE)["device"]
    directory = tmp_path / "recovered"; directory.mkdir()
    password = secrets.token_hex(20); path = directory / "generated.vault"
    create_v3_file(path, password, a.export_payload())
    restored = LocalVault(path, password)
    rm = Connections(config_dir=directory / "config", backend_factory=lambda: backend)
    assert rm.status(restored)["reconnect"] and not rm.status(restored)["connected"]
    assert rm.synchronize(restored, automatic=True) == {"skipped": True}
    connect(restored, rm, tmp_path, code=code)
    assert restored.metadata_value(STATE_NAMESPACE)["device"] != previous
    rm.synchronize(restored)


def test_connection_write_failure_cleans_owned_credentials_and_preserves_vault(tmp_path, monkeypatch):
    backend = GeneratedKeyring(); local, manager = profile(tmp_path / "a", backend)
    preview = manager.preview(local, "generated-session", options(tmp_path))
    before = local.vault_path.read_bytes()
    def fail(*args, **kwargs): raise OSError("Generated atomic failure")
    monkeypatch.setattr(local, "commit_sync_payload", fail)
    with pytest.raises(OSError): manager.apply(local, "generated-session", preview["preview_token"])
    assert not backend.records and local.vault_path.read_bytes() == before and not manager.status(local)["connected"]


def test_disconnect_stops_sync_even_if_windows_cleanup_needs_retry(tmp_path):
    backend = GeneratedKeyring(); local, manager = profile(tmp_path / "a", backend)
    local.add(SecretEntry(title="Generated kept account")); connect(local, manager, tmp_path)
    portable = project(local.export_payload())
    backend.fail_delete = True
    assert manager.disconnect(local)["cleanup_pending"]
    assert manager.status(local)["disabled"] and manager.synchronize(local, automatic=True) == {"skipped": True}
    with pytest.raises(ProtocolError): manager.code(local)
    backend.fail_delete = False
    assert not manager.disconnect(local)["cleanup_pending"]
    assert not backend.records and not manager.status(local)["connected"] and project(local.export_payload()) == portable


def test_api_confirmation_validation_and_lock_clear_pending_setup(runtime, tmp_path, monkeypatch):
    _, client, headers, auth, _ = runtime
    backend = GeneratedKeyring(); manager = Connections(config_dir=tmp_path / "config", backend_factory=lambda: backend)
    monkeypatch.setattr("vault_unified.api.routes.personal_sync.connections", manager)
    monkeypatch.setattr("vault_unified.personal_sync.connections.connections", manager)
    body = options(tmp_path); body["password"] = secrets.token_hex(20)
    invalid = client.post("/api/personal-sync/preview", headers=auth, json={**body, "automatic": body["password"]})
    assert invalid.status_code == 422 and body["password"] not in invalid.text
    preview = client.post("/api/personal-sync/preview", headers=auth, json=body)
    assert preview.status_code == 200 and preview.headers["Cache-Control"] == "no-store"
    token = preview.json()["preview_token"]
    for confirm in (False, "true"):
        assert client.post("/api/personal-sync/connect", headers=auth, json={"preview_token": token, "confirm": confirm}).status_code in (400, 422)
    assert client.post("/api/personal-sync/connect", headers=headers, json={"preview_token": token, "confirm": True}).status_code == 401
    assert client.post("/api/auth/lock", headers=auth).status_code == 200
    assert not manager._previews and not backend.records
    assert client.post("/api/personal-sync/connect", headers=auth, json={"preview_token": token, "confirm": True}).status_code == 401


def test_api_default_automatic_run_is_off_and_does_not_extend_idle_session(runtime, tmp_path, monkeypatch):
    _, client, _, auth, _ = runtime
    manager = Connections(config_dir=tmp_path / "config", backend_factory=lambda: pytest.fail("Disabled synchronization must not read credentials"))
    monkeypatch.setattr("vault_unified.api.routes.personal_sync.connections", manager)
    token = auth["Authorization"].split()[1]
    before = sessions._sessions[token].last_active
    response = client.post("/api/personal-sync/run", headers=auth, json={"automatic": True})
    assert response.status_code == 200 and response.json() == {"skipped": True}
    assert sessions._sessions[token].last_active == before


def test_lock_during_sync_download_refuses_late_merge_and_keeps_durable_outbox(runtime, tmp_path, monkeypatch):
    _, client, _, auth, _ = runtime
    backend = GeneratedKeyring(); manager = Connections(config_dir=tmp_path / "config", backend_factory=lambda: backend)
    monkeypatch.setattr("vault_unified.api.routes.personal_sync.connections", manager)
    local = sessions.get(auth["Authorization"].split()[1]).local
    local.add(SecretEntry(title="Generated locked sync")); connect(local, manager, tmp_path)
    state, _, secret = manager._credentials(local)
    store = manager._store(state["connection"], secret)
    entered, release = Event(), Event()
    class DelayedStore:
        def put(self, name, data): return store.put(name, data)
        def list(self): return store.list()
        def get(self, name):
            entered.set(); assert release.wait(5)
            return store.get(name)
    monkeypatch.setattr(manager, "_store", lambda *args, **kwargs: DelayedStore())
    with ThreadPoolExecutor() as pool:
        response = pool.submit(client.post, "/api/personal-sync/run", headers=auth, json={"automatic": False})
        assert entered.wait(5)
        before = local.vault_path.read_bytes()
        try: assert client.post("/api/auth/lock", headers=auth).status_code == 200
        finally: release.set()
        assert response.result(timeout=5).status_code == 401
    assert local.vault_path.read_bytes() == before and local.metadata_value(STATE_NAMESPACE)["outbox"]

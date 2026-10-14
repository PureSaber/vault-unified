from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event
import secrets

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient

from vault_unified.api.app import create_app
from vault_unified.api.deps import get_vault
from vault_unified.browser_pairing import browser_pairings
from vault_unified.session import SessionManager, sessions


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("VAULT_FILE", str(tmp_path / "generated.vault"))
    monkeypatch.setenv("VAULT_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("VAULT_BROWSER_HOST_EXE", "")
    sessions.set_system_blocked(False)
    browser_pairings.clear()
    master = secrets.token_hex(20)
    secret = secrets.token_hex(32)
    native_secret = secrets.token_hex(32)
    headers = {"X-Vault-Bootstrap": secret, "X-Vault-Client": "vault-unified-desktop", "X-Vault-Native": native_secret}
    app = create_app(bootstrap_secret=secret, native_secret=native_secret)
    with TestClient(app) as client:
        created = client.post("/api/auth/create", headers=headers, json={"password": master, "confirm_password": master})
        assert created.status_code == 200
        auth = {**headers, "Authorization": f"Bearer {created.json()['token']}"}
        yield app, client, headers, auth, master
    sessions.set_system_blocked(False)
    browser_pairings.clear()


def test_system_lock_revokes_all_sessions_and_browser_access_until_explicit_unlock(runtime):
    _, client, headers, auth, master = runtime
    second = client.post("/api/auth/unlock", headers=headers, json={"password": master}).json()["token"]
    code = client.post("/api/browser/pairing-code", headers=auth).json()["pairing_code"]
    origin = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"
    paired = client.post("/api/browser/pair", headers={"Origin": origin, "X-Vault-Browser-Pairing": code}, json={}).json()
    browser = {"Origin": origin, "X-Vault-Browser-Token": paired["browser_token"]}
    assert client.post("/api/browser/status", headers=browser).status_code == 200
    assert client.post("/api/auth/system-state", headers=headers, json={"blocked": True}).status_code == 200
    assert client.get("/api/entries", headers=auth).status_code == 401
    assert not sessions.is_unlocked(second)
    assert client.post("/api/browser/status", headers=browser).status_code == 401
    assert client.post("/api/auth/unlock", headers=headers, json={"password": master}).status_code == 423
    assert client.post("/api/auth/system-state", headers=headers, json={"blocked": False}).status_code == 200
    assert client.get("/api/entries", headers=auth).status_code == 401
    assert client.post("/api/auth/unlock", headers=headers, json={"password": master}).status_code == 200


def test_system_state_requires_desktop_bootstrap_and_boolean(runtime):
    _, client, headers, auth, _ = runtime
    for supplied in [{}, {"X-Vault-Client": "vault-unified-desktop"}, {"X-Vault-Bootstrap": headers["X-Vault-Bootstrap"]}]:
        assert client.post("/api/auth/system-state", headers=supplied, json={"blocked": True}).status_code == 403
    assert client.post("/api/auth/system-state", headers=headers, json={"blocked": "false"}).status_code == 422
    assert client.get("/api/entries", headers=auth).status_code == 200


@pytest.mark.parametrize("path,body", [("system-state", {"blocked": True}), ("renderer-reset", {})])
def test_private_response_already_in_flight_is_discarded_on_system_lock(runtime, path, body):
    app, client, headers, auth, _ = runtime
    started, release = Event(), Event()
    value = secrets.token_hex(24)

    @app.get("/api/generated-slow-read")
    def slow_read(vault=Depends(get_vault)):
        started.set()
        assert release.wait(5)
        return {"password": value}

    with ThreadPoolExecutor() as pool:
        request = pool.submit(client.get, "/api/generated-slow-read", headers=auth)
        assert started.wait(5)
        try:
            assert client.post(f"/api/auth/{path}", headers=headers, json=body).status_code == 200
        finally:
            release.set()
        result = request.result(timeout=5)
        assert result.status_code == 423
        assert value not in result.text


def test_renderer_reset_requires_native_capability_and_preserves_os_lock(runtime):
    _, client, headers, auth, master = runtime
    second = client.post("/api/auth/unlock", headers=headers, json={"password": master}).json()["token"]
    code = client.post("/api/browser/pairing-code", headers=auth).json()["pairing_code"]
    origin = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"
    paired = client.post("/api/browser/pair", headers={"Origin": origin, "X-Vault-Browser-Pairing": code}, json={}).json()
    browser = {"Origin": origin, "X-Vault-Browser-Token": paired["browser_token"]}
    renderer = {key: value for key, value in headers.items() if key != "X-Vault-Native"}
    assert client.post("/api/auth/renderer-reset", headers=renderer, json={}).status_code == 403
    assert client.get("/api/entries", headers=auth).status_code == 200
    assert client.post("/api/auth/renderer-reset", headers=headers, json={}).status_code == 200
    assert client.get("/api/entries", headers=auth).status_code == 401
    assert not sessions.is_unlocked(second)
    assert client.post("/api/browser/status", headers=browser).status_code == 401
    assert client.post("/api/auth/unlock", headers=headers, json={"password": master}).status_code == 200
    assert client.post("/api/auth/system-state", headers=headers, json={"blocked": True}).status_code == 200
    assert client.post("/api/auth/renderer-reset", headers=headers, json={}).status_code == 200
    assert client.post("/api/auth/unlock", headers=headers, json={"password": master}).status_code == 423


def test_delayed_password_unlock_cannot_register_after_a_lock(runtime, monkeypatch):
    _, _, _, _, master = runtime
    manager = SessionManager()
    started, release = Event(), Event()
    register = manager._register

    def delayed(vault, *, expected_epoch, **kwargs):
        started.set()
        assert release.wait(5)
        return register(vault, expected_epoch=expected_epoch, **kwargs)

    monkeypatch.setattr(manager, "_register", delayed)
    with ThreadPoolExecutor() as pool:
        request = pool.submit(manager.unlock, master)
        assert started.wait(5)
        manager.set_system_blocked(True)
        manager.set_system_blocked(False)
        release.set()
        with pytest.raises(PermissionError, match="cancelled"):
            request.result(timeout=5)
    assert not manager._sessions

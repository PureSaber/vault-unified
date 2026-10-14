from concurrent.futures import ThreadPoolExecutor
from threading import Event
import secrets

import pytest

from test_system_session_lock import runtime
from vault_unified.config import get_vault_path
from vault_unified.hello_unlock import hello_unlock
from vault_unified.session import sessions


@pytest.fixture(autouse=True)
def isolated_grants():
    hello_unlock.clear()
    yield
    hello_unlock.clear()


def prepare(client, auth):
    key = secrets.token_hex(32)
    response = client.post("/api/auth/hello/prepare", headers=auth, json={"key": key})
    assert response.status_code == 200
    return {"grant_id": response.json()["grant_id"], "key": key}


def test_hello_material_is_process_only_encrypted_and_needs_master_before_enable(runtime):
    _, client, headers, auth, master = runtime
    original = get_vault_path().read_bytes()
    grant = prepare(client, auth)
    record = hello_unlock._record
    assert master.encode() not in record.ciphertext
    assert "credential" not in vars(record) and "key" not in vars(record)
    assert get_vault_path().read_bytes() == original
    assert client.post("/api/auth/lock", headers=auth).status_code == 200
    response = client.post("/api/auth/hello/unlock", headers=headers, json=grant)
    assert response.status_code == 200
    hello_token = response.json()["token"]
    assert sessions.is_unlocked(hello_token)
    assert not sessions.master_authenticated(hello_token)
    reenroll = client.post("/api/auth/hello/prepare", headers={**headers, "Authorization": f"Bearer {hello_token}"}, json={"key": secrets.token_hex(32)})
    assert reenroll.status_code == 409
    sessions.lock_all()
    assert client.post("/api/auth/hello/unlock", headers=headers, json=grant).status_code == 200
    assert get_vault_path().read_bytes() == original


def test_renderer_bootstrap_and_browser_tokens_cannot_access_hello_endpoints(runtime):
    _, client, headers, auth, _ = runtime
    grant = prepare(client, auth)
    renderer = {key: value for key, value in auth.items() if key != "X-Vault-Native"}
    for path, body in [("/api/auth/hello/prepare", {"key": grant["key"]}), ("/api/auth/hello/unlock", grant)]:
        response = client.post(path, headers=renderer, json=body)
        assert response.status_code == 403
    assert client.delete("/api/auth/hello", headers=renderer).status_code == 403
    assert client.post("/api/auth/system-state", headers=renderer, json={"blocked": False}).status_code == 403
    invalid = secrets.token_hex(16)
    response = client.post("/api/auth/hello/prepare", headers=auth, json={"key": invalid})
    assert response.status_code == 422 and invalid not in response.text


def test_wrong_key_clear_and_restart_prevent_quick_unlock(runtime):
    _, client, headers, auth, _ = runtime
    grant = prepare(client, auth)
    response = client.post("/api/auth/hello/unlock", headers=headers, json={**grant, "key": secrets.token_hex(32)})
    assert response.status_code == 401
    assert hello_unlock._record is None
    grant = prepare(client, auth)
    assert client.delete("/api/auth/hello", headers=headers).status_code == 200
    assert client.post("/api/auth/hello/unlock", headers=headers, json=grant).status_code == 401


def test_system_lock_blocks_hello_and_resume_needs_new_explicit_request(runtime):
    _, client, headers, auth, _ = runtime
    grant = prepare(client, auth)
    assert client.post("/api/auth/system-state", headers=headers, json={"blocked": True}).status_code == 200
    assert client.post("/api/auth/hello/unlock", headers=headers, json=grant).status_code == 423
    assert client.post("/api/auth/system-state", headers=headers, json={"blocked": False}).status_code == 200
    assert not sessions._sessions
    assert client.post("/api/auth/hello/unlock", headers=headers, json=grant).status_code == 200


def test_disable_during_unseal_rejects_and_revokes_the_late_session(runtime, monkeypatch):
    _, client, headers, auth, _ = runtime
    grant = prepare(client, auth)
    sessions.lock_all()
    started, release = Event(), Event()
    unlock = sessions.unlock

    def delayed(*args, **kwargs):
        started.set()
        assert release.wait(5)
        return unlock(*args, **kwargs)

    monkeypatch.setattr(sessions, "unlock", delayed)
    with ThreadPoolExecutor() as pool:
        request = pool.submit(client.post, "/api/auth/hello/unlock", headers=headers, json=grant)
        assert started.wait(5)
        try:
            assert client.delete("/api/auth/hello", headers=headers).status_code == 200
        finally:
            release.set()
        assert request.result(timeout=5).status_code == 401
    assert not sessions._sessions

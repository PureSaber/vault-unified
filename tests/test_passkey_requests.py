import copy
import json
import secrets
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest
from fido2.server import Fido2Server

from test_system_session_lock import runtime
from vault_unified.passkey_requests import requests
from vault_unified import passkey_requests as module
from vault_unified.session import sessions
from vault_unified.browser_pairing import browser_pairings
from vault_unified.passkeys import credentials_for
from vault_unified.organization import prepare_action


@pytest.fixture(autouse=True)
def isolated_requests():
    requests.clear()
    yield
    requests.clear()


def browser(runtime):
    _, client, _, auth, _ = runtime
    code = client.post("/api/browser/pairing-code", headers=auth).json()["pairing_code"]
    origin = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"
    result = client.post("/api/browser/pair", headers={"Origin": origin, "X-Vault-Browser-Pairing": code}, json={}).json()
    return {"Origin": origin, "X-Vault-Browser-Token": result["browser_token"]}


def registration():
    server = Fido2Server({"id": "example.com", "name": "Generated RP"})
    options, state = server.register_begin({"id": secrets.token_bytes(16), "name": "generated", "displayName": "Generated account"}, user_verification="required")
    return server, state, {"operation": "create", "origin": "https://login.example.com", "options": dict(options)["publicKey"]}


def begin(client, headers, body):
    result = client.post("/api/browser/passkeys/begin", headers=headers, json=body)
    assert result.status_code == 200
    return result.json()["request_id"]


def test_browser_requires_desktop_verification_for_registration_and_sign_in(runtime):
    _, client, bootstrap, auth, master = runtime
    headers = browser(runtime)
    server, state, body = registration()
    identifier = begin(client, headers, body)
    vault = sessions.get(auth["Authorization"].split()[1])
    original = vault.vault_path.read_bytes()
    assert client.get("/api/passkeys/pending", headers=headers).status_code == 403
    assert client.get("/api/passkeys/pending", headers=bootstrap).status_code == 401
    pending = client.get("/api/passkeys/pending", headers=auth).json()["items"][0]
    assert pending["rp_id"] == "example.com" and pending["origin"] == body["origin"]
    approval = {"request_id": identifier, "confirm": True, "password": master}
    assert client.post("/api/passkeys/approve", headers=headers, json=approval).status_code == 403
    assert client.post("/api/passkeys/approve", headers=auth, json={**approval, "confirm": False}).status_code == 400
    wrong = secrets.token_hex(24)
    failed = client.post("/api/passkeys/approve", headers=auth, json={**approval, "password": wrong})
    assert failed.status_code == 400 and wrong not in failed.text and master not in failed.text
    assert vault.vault_path.read_bytes() == original
    assert client.post("/api/passkeys/approve", headers=auth, json=approval).json() == {"approved": True, "changed": True}
    assert client.post("/api/passkeys/approve", headers=auth, json=approval).status_code == 400
    response = client.post("/api/browser/passkeys/status", headers=headers, json={"request_id": identifier}).json()
    assert response["status"] == "complete"
    attested = server.register_complete(state, response["credential"])
    entry = vault.local.list_entries()[0]; key = credentials_for(entry)[0]
    assert key["private_key"] not in json.dumps(response)
    assert client.post("/api/browser/passkeys/cancel", headers=headers, json={"request_id": identifier}).status_code == 200
    options, state = server.authenticate_begin([attested.credential_data], user_verification="required")
    identifier = begin(client, headers, {"operation": "get", "origin": body["origin"], "options": dict(options)["publicKey"]})
    choices = client.get("/api/passkeys/pending", headers=auth).json()["items"][0]["choices"]
    assert len(choices) == 1 and key["private_key"] not in json.dumps(choices)
    assert client.post("/api/passkeys/approve", headers=auth, json={**approval, "request_id": identifier}).status_code == 400
    approved = client.post("/api/passkeys/approve", headers=auth, json={**approval, "request_id": identifier, "entry_id": entry.id, "credential_id": key["id"]})
    assert approved.json() == {"approved": True, "changed": False}
    signed = client.post("/api/browser/passkeys/status", headers=headers, json={"request_id": identifier}).json()["credential"]
    assert server.authenticate_complete(state, [attested.credential_data], signed) == attested.credential_data
    excluded = copy.deepcopy(body)
    excluded["options"]["excludeCredentials"] = [{"type": "public-key", "id": key["id"]}]
    excluded_id = begin(client, headers, excluded)
    result = client.post("/api/passkeys/approve", headers=auth, json={**approval, "request_id": excluded_id})
    assert result.json() == {"approved": False, "changed": False}
    assert client.post("/api/browser/passkeys/status", headers=headers, json={"request_id": excluded_id}).json() == {"status": "excluded"}
    assert len(vault.local.list_entries()) == 1
    vault.local.commit_entry(prepare_action(entry, "archive", tags=[]), create=False, expected_updated_at=entry.updated_at)
    assert client.post("/api/browser/passkeys/begin", headers=headers, json={"operation": "get", "origin": body["origin"], "options": dict(options)["publicKey"]}).json() == {"status": "fallback"}


@pytest.mark.parametrize("action", ["cancel", "reject", "fallback", "expire", "disconnect", "lock"])
def test_cancellation_timeout_revocation_and_lock_never_create_credentials(runtime, action):
    _, client, _, auth, master = runtime
    headers = browser(runtime); _, _, body = registration()
    identifier = begin(client, headers, body)
    token = auth["Authorization"].split()[1]
    vault = sessions.get(token); before = vault.vault_path.read_bytes()
    if action == "cancel": client.post("/api/browser/passkeys/cancel", headers=headers, json={"request_id": identifier})
    elif action in {"reject", "fallback"}: client.post("/api/passkeys/reject", headers=auth, json={"request_id": identifier, "fallback": action == "fallback"})
    elif action == "expire": requests._pending[identifier].expires = 0
    elif action == "disconnect": client.post("/api/browser/disconnect", headers=headers)
    else: sessions.lock(token)
    result = client.post("/api/passkeys/approve", headers=auth, json={"request_id": identifier, "confirm": True, "password": master})
    assert result.status_code in {400, 401}
    assert before == vault.vault_path.read_bytes() and not vault.local.list_entries()
    if action == "lock": assert identifier not in requests._pending


@pytest.mark.parametrize("interruption", ["lock", "cancel", "edit", "write-failure"])
def test_inflight_verification_cannot_commit_after_cancel_or_stale_edit(runtime, monkeypatch, interruption):
    _, client, _, auth, master = runtime
    headers = browser(runtime); _, _, body = registration(); identifier = begin(client, headers, body)
    token = auth["Authorization"].split()[1]; vault = sessions.get(token)
    entered, release = Event(), Event()
    original = module.decrypt_payload
    def paused(*args):
        value = original(*args); entered.set(); assert release.wait(10); return value
    monkeypatch.setattr(module, "decrypt_payload", paused)
    if interruption == "write-failure":
        def fail(*args, **kwargs): raise OSError("generated private storage error")
        monkeypatch.setattr(vault.local, "commit_sync_payload", fail)
    with ThreadPoolExecutor() as pool:
        task = pool.submit(client.post, "/api/passkeys/approve", headers=auth, json={"request_id": identifier, "confirm": True, "password": master})
        assert entered.wait(10)
        try:
            if interruption == "lock": sessions.lock(token)
            elif interruption == "cancel": requests.cancel_browser(headers["X-Vault-Browser-Token"], headers["Origin"], identifier)
            elif interruption == "edit": vault.add("Generated later edit", auto_push=False)
            before = vault.vault_path.read_bytes()
        finally: release.set()
        response = task.result(timeout=10)
    assert response.status_code in {400, 401, 409}
    assert vault.vault_path.read_bytes() == before
    assert all(not credentials_for(entry) for entry in vault.local.list_entries())
    assert "generated private storage error" not in response.text and master not in response.text


def test_polling_does_not_extend_idle_and_other_scopes_cannot_approve_or_read(runtime):
    _, client, bootstrap, auth, master = runtime
    headers = browser(runtime); _, _, body = registration(); identifier = begin(client, headers, body)
    token = auth["Authorization"].split()[1]
    sessions._sessions[token].last_active -= 100
    before = sessions._sessions[token].last_active
    for _ in range(2):
        assert client.get("/api/passkeys/pending", headers=auth).status_code == 200
        assert client.post("/api/browser/passkeys/status", headers=headers, json={"request_id": identifier}).status_code == 200
    assert before == sessions._sessions[token].last_active
    other = client.post("/api/auth/unlock", headers=bootstrap, json={"password": master}).json()["token"]
    other_auth = {**bootstrap, "Authorization": "Bearer " + other}
    assert client.get("/api/passkeys/pending", headers=other_auth).json() == {"items": []}
    assert client.post("/api/passkeys/approve", headers=other_auth, json={"request_id": identifier, "confirm": True, "password": master}).status_code == 400
    assert client.post("/api/browser/passkeys/status", headers={**headers, "Origin": "chrome-extension://bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}, json={"request_id": identifier}).status_code == 400
    result = client.post("/api/passkeys/approve", headers=auth, json={"request_id": identifier, "confirm": "yes", "password": master})
    assert result.status_code == 422 and master not in result.text


def test_cancel_can_precede_begin_and_begin_retries_keep_one_request(runtime):
    _, client, _, auth, _ = runtime
    headers = browser(runtime); _, _, body = registration()
    identifier = str(uuid4()); body["request_id"] = identifier
    assert begin(client, headers, body) == identifier
    assert begin(client, headers, body) == identifier
    assert len(client.get("/api/passkeys/pending", headers=auth).json()["items"]) == 1
    client.post("/api/browser/passkeys/cancel", headers=headers, json={"request_id": identifier})
    assert client.post("/api/browser/passkeys/begin", headers=headers, json=body).status_code == 400
    identifier = str(uuid4()); body["request_id"] = identifier
    client.post("/api/browser/passkeys/cancel", headers=headers, json={"request_id": identifier})
    assert client.post("/api/browser/passkeys/begin", headers=headers, json=body).status_code == 400
    assert client.get("/api/passkeys/pending", headers=auth).json() == {"items": []}

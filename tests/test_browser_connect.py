"""Desktop-approved first connection with number matching (docs/browser-connection-approval.md)."""
from __future__ import annotations

import base64
import secrets
import time
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from vault_unified import browser_connect
from vault_unified.api.app import create_app
from vault_unified.browser_connect import browser_connects
from vault_unified.browser_discovery import EXTENSION_ORIGINS
from vault_unified.browser_pairing import browser_pairings
from vault_unified.browser_trust import MAX_DEVICES, browser_trust
from vault_unified.session import sessions

from tests.test_browser_trust import MemoryCredentials, signature

ORIGIN = next(iter(EXTENSION_ORIGINS))
OTHER = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"
NONCE = "generated-connect-nonce-0123456789abcdef"


def identity():
    private = ec.generate_private_key(ec.SECP256R1())
    encoded = base64.b64encode(private.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).decode()
    return private, encoded


@pytest.fixture
def backend(tmp_path, monkeypatch):
    value = MemoryCredentials()
    monkeypatch.setenv("VAULT_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setattr("vault_unified.browser_trust.get_approved_backend", lambda: value)
    return value


@pytest.fixture
def app(tmp_path, monkeypatch, backend):
    path = tmp_path / "generated.vault"
    master, bootstrap = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    monkeypatch.setenv("VAULT_FILE", str(path))
    sessions.lock_all()
    browser_pairings.clear()
    browser_connects.clear()
    token, _ = sessions.create_v3(master, master, vault_path=path)
    with TestClient(create_app(bootstrap_secret=bootstrap, connect_nonce=NONCE)) as client:
        yield SimpleNamespace(client=client, token=token, master=master, path=path,
                              desktop={"X-Vault-Bootstrap": bootstrap, "Authorization": f"Bearer {token}"})
    sessions.lock_all()
    browser_pairings.clear()
    browser_connects.clear()


def ask(app, public=None, origin=ORIGIN, nonce=NONCE, name="Generated Chrome"):
    headers = {"Origin": origin, **({"X-Vault-Connect-Nonce": nonce} if nonce is not None else {})}
    return app.client.post("/api/browser/connect/request", headers=headers,
                           json={"public_key": public or identity()[1], "device_name": name})


def status(app, started, origin=ORIGIN, secret=None):
    return app.client.post("/api/browser/connect/status", headers={"Origin": origin},
                           json={"request_id": started["request_id"], "poll_secret": secret or started["poll_secret"]})


def pending(app):
    response = app.client.get("/api/browser/connect/pending", headers=app.desktop)
    assert response.status_code == 200
    return response.json()["items"]


def decide(app, path, request_id, code=""):
    return app.client.post(f"/api/browser/connect/{path}", headers=app.desktop, json={"request_id": request_id, "code": code})


def test_number_matching_approval_enrolls_only_at_claim_and_resume_issues_the_token(app, backend):
    private, public = identity()
    started = ask(app, public).json()
    assert set(started) == {"request_id", "poll_secret", "code", "expires_in_seconds"}
    assert len(started["code"]) == 6 and started["code"].isdigit()
    [item] = pending(app)
    assert item["device_name"] == "Generated Chrome"
    assert started["code"] in item["choices"] and len(set(item["choices"])) == 3
    # The choices and their order are fixed, so polling cannot reveal the answer.
    assert pending(app)[0]["choices"] == item["choices"]
    assert "code" not in item and "poll_secret" not in str(item)
    assert status(app, started).json()["state"] == "pending"

    assert decide(app, "approve", item["id"], started["code"]).json() == {"approved": True}
    assert browser_trust.device_count() == 0, "approval alone enrolls nothing"
    claimed = status(app, started).json()
    assert claimed["state"] == "approved" and set(claimed) == {"state", "device_id"}
    assert browser_trust.device_count() == 1
    # A lost response can be re-read; it never enrolls a second device.
    assert status(app, started).json() == claimed
    assert browser_trust.device_count() == 1
    assert pending(app) == []

    issued = app.client.post("/api/browser/device/challenge", headers={"Origin": ORIGIN},
                             json={"device_id": claimed["device_id"], "action": "resume"}).json()
    resumed = app.client.post("/api/browser/device/prove", headers={"Origin": ORIGIN}, json={
        "device_id": claimed["device_id"], "action": "resume", "challenge_id": issued["challenge_id"],
        "signature": signature(private, issued["message"])})
    assert resumed.status_code == 200 and resumed.json()["browser_token"]


def test_wrong_pick_denies_once_and_starts_the_refusal(app):
    started = ask(app).json()
    [item] = pending(app)
    wrong = next(choice for choice in item["choices"] if choice != started["code"])
    assert decide(app, "approve", item["id"], wrong).json() == {"approved": False}
    assert decide(app, "approve", item["id"], started["code"]).status_code == 404
    assert status(app, started).json() == {"state": "denied"}
    assert status(app, started).status_code == 404, "a terminal result is reported once"
    assert ask(app).status_code == 429
    assert browser_trust.device_count() == 0


def test_identity_nonce_and_guard_checks_come_first(app):
    assert ask(app, origin=OTHER).status_code == 403
    assert ask(app, nonce=None).status_code == 403
    assert ask(app, nonce="wrong").status_code == 403
    sessions.lock_all()
    # Without the nonce a caller cannot learn whether the vault is unlocked.
    assert ask(app, nonce="wrong").status_code == 403
    assert ask(app).status_code == 423
    for path, method in (("pending", "get"), ("approve", "post"), ("deny", "post"), ("deny-all", "post")):
        response = getattr(app.client, method)(f"/api/browser/connect/{path}", headers={"Authorization": app.desktop["Authorization"]},
                                                **({} if method == "get" else {"json": {"request_id": "x"}}))
        assert response.status_code == 403, "desktop decisions need the bootstrap secret"
    client = TestClient(create_app(bootstrap_secret=secrets.token_urlsafe(32)))
    assert client.post("/api/browser/connect/request", headers={"Origin": ORIGIN, "X-Vault-Connect-Nonce": ""},
                       json={"public_key": identity()[1]}).status_code == 403, "no nonce published, no requests"


def test_status_requires_the_poll_secret_and_origin(app):
    started = ask(app).json()
    assert status(app, started, secret="x" * 43).status_code == 404
    assert status(app, started, origin=OTHER).status_code == 403
    assert status(app, {"request_id": "unknown", "poll_secret": started["poll_secret"]}).status_code == 404
    assert status(app, started).json()["state"] == "pending"


def test_lock_ends_requests_as_locked_and_approval_needs_the_same_vault(app):
    started = ask(app).json()
    [item] = pending(app)
    sessions.lock(app.token)
    assert status(app, started).json() == {"state": "locked"}
    token, _ = sessions.unlock(app.master, vault_path=app.path)
    app.desktop["Authorization"] = f"Bearer {token}"
    assert pending(app) == []
    assert decide(app, "approve", item["id"], started["code"]).status_code == 404


def test_lock_after_approval_prevents_the_claim(app):
    started = ask(app).json()
    [item] = pending(app)
    assert decide(app, "approve", item["id"], started["code"]).json()["approved"]
    sessions.lock_all()
    assert status(app, started).json() == {"state": "locked"}
    assert browser_trust.device_count() == 0


def test_a_lock_during_enrollment_revokes_the_new_device(app, monkeypatch):
    started = ask(app).json()
    [item] = pending(app)
    decide(app, "approve", item["id"], started["code"])
    enroll = browser_trust.enroll

    def enroll_then_lock(*args):
        record = enroll(*args)
        sessions.lock_all()
        return record

    monkeypatch.setattr(browser_trust, "enroll", enroll_then_lock)
    assert status(app, started).json() == {"state": "locked"}
    assert browser_trust.device_count() == 0


def test_deny_deny_all_limits_and_duplicates(app):
    first = ask(app).json()
    assert decide(app, "deny", pending(app)[0]["id"]).json() == {"denied": True}
    assert status(app, first).json() == {"state": "denied"}

    _, public = identity()
    assert ask(app, public).status_code == 200
    assert ask(app, public).status_code == 409, "one pending request per key"
    assert ask(app).status_code == 200
    assert ask(app).status_code == 200
    assert ask(app).status_code == 429, "at most 3 pending"
    assert decide(app, "deny-all", "").json() == {"denied": 3}
    assert pending(app) == []
    assert ask(app).status_code == 429, "Deny all starts a refusal"


def test_rate_limit_counts_only_accepted_requests(app, monkeypatch):
    for _ in range(20):
        assert ask(app, nonce="wrong").status_code == 403
    for _ in range(browser_connect.RATE_LIMIT):
        started = ask(app)
        assert started.status_code == 200
        decide(app, "deny", pending(app)[0]["id"])
    browser_connects._refuse_until = 0.0
    assert ask(app).status_code == 429


def test_expiry_and_device_limit(app, monkeypatch):
    started = ask(app).json()
    now = time.monotonic()
    with monkeypatch.context() as later:
        later.setattr(browser_connect, "time", SimpleNamespace(monotonic=lambda: now + browser_connect.CONNECT_TTL_SECONDS + 1))
        assert status(app, started).json() == {"state": "expired"}
    monkeypatch.setattr(browser_trust, "device_count", lambda: MAX_DEVICES)
    response = ask(app)
    assert response.status_code == 409 and response.json()["detail"]["code"] == "device_limit"


def test_invalid_input_is_rejected_without_detail(app):
    assert ask(app, public="not-a-key").status_code == 422
    assert ask(app, name="bad\nname").status_code == 422


def approved(app):
    started = ask(app).json()
    [item] = pending(app)
    assert decide(app, "approve", item["id"], started["code"]).json()["approved"]
    return started


def test_a_concurrent_status_during_the_claim_waits_and_enrolls_once(app, monkeypatch):
    started = approved(app)
    enroll, nested = browser_trust.enroll, []

    def enroll_while_polled(*args):
        nested.append(status(app, started).json())
        return enroll(*args)

    monkeypatch.setattr(browser_trust, "enroll", enroll_while_polled)
    claimed = status(app, started).json()
    assert nested == [{"state": "pending", "remaining_seconds": nested[0]["remaining_seconds"]}]
    assert claimed["state"] == "approved" and browser_trust.device_count() == 1


def test_claim_never_registers_the_native_host(app, monkeypatch):
    calls = []
    monkeypatch.setattr("vault_unified.browser_discovery.register", lambda origin: calls.append(origin) or True)
    monkeypatch.setattr("vault_unified.browser_discovery.register_fixed", lambda: calls.append("fixed") or True)
    assert status(app, approved(app)).json()["state"] == "approved"
    assert calls == [], "only release-build startup registers, so a development build cannot take over"


def test_a_failed_revocation_after_a_lock_hands_the_device_over(app, monkeypatch):
    from vault_unified.browser_trust import BrowserTrustUnavailable
    started = approved(app)
    enroll = browser_trust.enroll

    def enroll_then_lock(*args):
        record = enroll(*args)
        sessions.lock_all()
        return record

    def unavailable(*args):
        raise BrowserTrustUnavailable("generated failure")

    monkeypatch.setattr(browser_trust, "enroll", enroll_then_lock)
    monkeypatch.setattr(browser_trust, "revoke", unavailable)
    claimed = status(app, started).json()
    assert claimed["state"] == "approved", "the extension keeps the key of the device that exists"
    assert status(app, started).json() == claimed


def test_single_session_lock_and_idle_expiry_end_requests(app, monkeypatch):
    started = ask(app).json()
    sessions.lock(app.token)
    assert status(app, started).json() == {"state": "locked"}
    token, _ = sessions.unlock(app.master, vault_path=app.path)
    started = ask(app).json()
    sessions._sessions[token].last_active -= 31 * 60
    with pytest.raises(PermissionError):
        sessions.get(token)
    assert status(app, started).json() == {"state": "locked"}


def test_format_characters_never_reach_the_desktop_name(app):
    ask(app, name="Generated\u202e emorhC")
    assert pending(app)[0]["device_name"] == "Generated emorhC"

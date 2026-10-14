from __future__ import annotations

import base64
import json
import secrets
import sys
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from fastapi.testclient import TestClient

from vault_unified.api.app import create_app
from vault_unified.browser_pairing import browser_pairings
from vault_unified.browser_trust import BrowserTrustStore, BrowserTrustError, BrowserTrustUnavailable, browser_trust
from vault_unified.session import sessions

ORIGIN = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"
OTHER = "chrome-extension://bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


class MemoryCredentials:
    def __init__(self):
        self.records = {}
        self.fail_write = None

    def get_password(self, service, account):
        return self.records.get((service, account))

    def set_password(self, service, account, value):
        if self.fail_write and account.endswith(self.fail_write):
            raise OSError("generated failure")
        self.records[service, account] = value

    def delete_password(self, service, account):
        del self.records[service, account]


def identity():
    private = ec.generate_private_key(ec.SECP256R1())
    encoded = base64.b64encode(private.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).decode()
    return private, encoded


def signature(private, message):
    r, s = decode_dss_signature(private.sign(message.encode(), ec.ECDSA(hashes.SHA256())))
    return base64.b64encode(r.to_bytes(32, "big") + s.to_bytes(32, "big")).decode()


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
    token, vault = sessions.create_v3(master, master, vault_path=path)
    desktop = {"X-Vault-Bootstrap": bootstrap, "Authorization": f"Bearer {token}"}
    with TestClient(create_app(bootstrap_secret=bootstrap)) as client:
        private, public = identity()
        code = client.post("/api/browser/pairing-code", headers=desktop).json()["pairing_code"]
        paired = client.post("/api/browser/pair", headers={"Origin": ORIGIN, "X-Vault-Browser-Pairing": code},
                             json={"remember_connection": True, "public_key": public, "device_name": "Generated Chrome"})
        assert paired.status_code == 200
        data = paired.json()
        yield SimpleNamespace(client=client, desktop=desktop, master=master, bootstrap=bootstrap,
                              private=private, device_id=data["device_id"], path=path, vault=vault,
                              browser={"Origin": ORIGIN, "X-Vault-Browser-Token": data["browser_token"]})
    sessions.lock_all()
    browser_pairings.clear()


def challenge(app, action="resume", origin=ORIGIN):
    return app.client.post("/api/browser/device/challenge", headers={"Origin": origin},
                           json={"device_id": app.device_id, "action": action})


def proof(app, issued, action="resume", private=None, origin=ORIGIN):
    return {"device_id": app.device_id, "action": action, "challenge_id": issued["challenge_id"],
            "signature": signature(private or app.private, issued["message"])}


def prove(app, body, origin=ORIGIN):
    return app.client.post("/api/browser/device/prove", headers={"Origin": origin}, json=body)


def test_trust_survives_memory_restart_but_never_unlocks_vault(app, backend):
    assert app.client.post("/api/browser/status", headers=app.browser).status_code == 200
    saved = json.dumps(list(backend.records.values()))
    assert app.master not in saved and app.browser["X-Vault-Browser-Token"] not in saved
    sessions.lock_all()
    browser_pairings.clear()
    assert challenge(app).status_code == 423
    assert app.client.post("/api/browser/status", headers=app.browser).status_code == 401
    unlocked = app.client.post("/api/auth/unlock", headers={"X-Vault-Bootstrap": app.bootstrap},
                               json={"password": app.master, "remember": False})
    assert unlocked.status_code == 200
    issued = challenge(app).json()
    body = proof(app, issued)
    result = prove(app, body)
    assert result.status_code == 200
    assert result.json()["browser_token"] != app.browser["X-Vault-Browser-Token"]
    assert prove(app, body).status_code == 401  # Consumed once, including failed proofs.
    assert len(BrowserTrustStore().list_for(sessions.browser_binding(unlocked.json()["token"]))) == 1


@pytest.mark.parametrize("failure", ["wrong-key", "wrong-origin", "wrong-action", "expired", "locked", "revoked"])
def test_proof_failures_never_issue_access(app, monkeypatch, failure):
    issued = challenge(app).json()
    body = proof(app, issued, private=identity()[0] if failure == "wrong-key" else None)
    if failure == "wrong-action":
        body["action"] = "revoke"
    elif failure == "expired":
        current = __import__("time").monotonic()
        monkeypatch.setattr("vault_unified.browser_trust.time.monotonic", lambda: current + 61)
    elif failure == "locked":
        sessions.lock_all()
    elif failure == "revoked":
        assert app.client.delete(f"/api/browser/devices/{app.device_id}", headers=app.desktop).status_code == 200
    result = prove(app, body, origin=OTHER if failure == "wrong-origin" else ORIGIN)
    assert result.status_code == (423 if failure == "locked" else 401)
    assert "browser_token" not in result.text
    assert prove(app, body).status_code == 401


def test_revocation_kills_tokens_and_cannot_be_cross_vault(app, tmp_path):
    password = secrets.token_urlsafe(32)
    token, _ = sessions.create_v3(password, password, vault_path=tmp_path / "other.vault")
    other_desktop = {**app.desktop, "Authorization": f"Bearer {token}"}
    assert app.client.get("/api/browser/devices", headers=other_desktop).json()["devices"] == []
    assert app.client.delete(f"/api/browser/devices/{app.device_id}", headers=other_desktop).status_code == 401
    assert app.client.get("/api/browser/devices", headers=app.browser).status_code == 403
    assert app.client.delete(f"/api/browser/devices/{app.device_id}", headers=app.desktop).status_code == 200
    assert app.client.delete(f"/api/browser/devices/{app.device_id}", headers=app.desktop).status_code == 200
    assert app.client.post("/api/browser/status", headers=app.browser).status_code == 401
    assert challenge(app).status_code == 401


def test_browser_can_revoke_its_own_identity_while_locked(app):
    sessions.lock_all()
    issued = challenge(app, "revoke").json()
    assert prove(app, proof(app, issued, "revoke")).status_code == 200
    assert challenge(app, "revoke").status_code == 401


def test_no_bootstrap_bypass_to_other_paths_or_validation_leaks(app):
    assert challenge(app, origin="https://attacker.invalid").status_code == 401
    secret = secrets.token_urlsafe(40)
    result = prove(app, {"device_id": secret, "signature": secret})
    assert result.status_code == 422 and secret not in result.text
    assert app.client.post("/api/auth/unlock", headers={"Origin": ORIGIN}, json={"password": secret}).status_code == 403
    assert app.client.get("/api/browser/device/challenge", headers={"Origin": ORIGIN}).status_code == 403


def test_keyring_corruption_and_unavailability_fail_closed(app, backend, monkeypatch):
    index_key = next(key for key in backend.records if key[1].endswith(":index"))
    previous = backend.records[index_key]
    backend.records[index_key] = '{"broken": true}'
    assert challenge(app).status_code == 503
    backend.records[index_key] = previous
    monkeypatch.setattr("vault_unified.browser_trust.get_approved_backend", lambda: (_ for _ in ()).throw(OSError()))
    assert challenge(app).status_code == 503
    assert app.client.post("/api/browser/status", headers=app.browser).status_code == 401


def test_partial_index_write_does_not_resurrect_revocation(app, backend):
    backend.fail_write = ":index"
    assert app.client.delete(f"/api/browser/devices/{app.device_id}", headers=app.desktop).status_code == 503
    assert app.client.post("/api/browser/status", headers=app.browser).status_code == 401
    backend.fail_write = None
    assert app.client.delete(f"/api/browser/devices/{app.device_id}", headers=app.desktop).status_code == 200


def test_enrollment_failure_removes_unindexed_identity(backend):
    store = BrowserTrustStore()
    backend.fail_write = ":index"
    with pytest.raises(BrowserTrustUnavailable):
        store.enroll(("generated-path", "vault", "key"), ORIGIN, identity()[1], "Browser")
    assert backend.records == {}


@pytest.mark.parametrize("public", ["invalid", base64.b64encode(b"generated-invalid-key").decode()])
def test_invalid_public_key_never_persists(backend, public):
    with pytest.raises(BrowserTrustError):
        BrowserTrustStore().enroll(("generated-path", "vault", "key"), ORIGIN, public, "Browser")
    assert backend.records == {}


@pytest.mark.skipif(sys.platform != "win32", reason="Windows credential store integration")
def test_windows_credential_store_roundtrip_in_isolated_namespace(tmp_path, monkeypatch):
    monkeypatch.setenv("VAULT_CONFIG_DIR", str(tmp_path / secrets.token_hex(12)))
    store = BrowserTrustStore()
    binding = (str(tmp_path / "generated.vault"), secrets.token_hex(16), secrets.token_hex(16))
    private, public = identity()
    device = None
    try:
        device = store.enroll(binding, ORIGIN, public, "Generated Windows test")
        reopened = BrowserTrustStore()
        issued = reopened.challenge(device["id"], ORIGIN, "resume")
        assert reopened.verify(device["id"], ORIGIN, "resume", issued["challenge_id"], signature(private, issued["message"]))["id"] == device["id"]
        reopened.revoke(binding, device["id"])
        assert reopened.list_for(binding) == []
    finally:
        if device:
            store.revoke(binding, device["id"])
        if store._read("index") is not None:
            store._delete("index")

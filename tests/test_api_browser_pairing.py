from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("fastapi")

from vault_unified.api.app import create_app
from vault_unified.manager import UnifiedVault


BOOTSTRAP_SECRET = "browser-bootstrap-secret-0123456789abcdef"
ORIGIN = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"


@pytest.fixture
def client(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        vault_file = Path(tmp) / "secrets.vault"
        monkeypatch.setenv("VAULT_FILE", str(vault_file))
        monkeypatch.setattr("vault_unified.config.get_vault_path", lambda: vault_file)
        UnifiedVault.create(vault_file, "test123")
        app = create_app(bootstrap_secret=BOOTSTRAP_SECRET, instance_id="browser-api-test")
        with TestClient(app) as test_client:
            yield test_client


def _desktop_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/auth/unlock",
        json={"password": "test123", "remember": False},
        headers={"X-Vault-Bootstrap": BOOTSTRAP_SECRET},
    )
    assert response.status_code == 200
    return {
        "X-Vault-Bootstrap": BOOTSTRAP_SECRET,
        "Authorization": f"Bearer {response.json()['token']}",
    }


def test_extension_pairing_is_one_time_origin_bound_and_lost_on_lock(client: TestClient) -> None:
    headers = _desktop_headers(client)
    entry = client.post(
        "/api/entries",
        headers=headers,
        json={
            "title": "Example",
            "username": "person@example.test",
            "password": "secret-value",
            "url": "https://www.example.test/login",
        },
    )
    assert entry.status_code == 200

    code = client.post("/api/browser/pairing-code", headers=headers)
    assert code.status_code == 200
    pairing = client.post(
        "/api/browser/pair",
        headers={
            "Origin": ORIGIN,
            "X-Vault-Browser-Pairing": code.json()["pairing_code"],
        },
        json={},
    )
    assert pairing.status_code == 200
    browser_headers = {"Origin": ORIGIN, "X-Vault-Browser-Token": pairing.json()["browser_token"]}

    matches = client.get(
        "/api/browser/matches?url=https%3A%2F%2Fexample.test%2Fsignin",
        headers=browser_headers,
    )
    assert matches.status_code == 200
    assert matches.json()["matches"] == [{
        "id": entry.json()["id"],
        "title": "Example",
        "username": "person@example.test",
    }]
    assert "secret-value" not in matches.text

    fill = client.post(
        "/api/browser/fill",
        headers=browser_headers,
        json={"entry_id": entry.json()["id"], "url": "https://example.test/signin"},
    )
    assert fill.status_code == 200
    assert fill.json() == {"username": "person@example.test", "password": "secret-value"}

    wrong_origin = client.get(
        "/api/browser/matches?url=https%3A%2F%2Fexample.test",
        headers={**browser_headers, "Origin": "chrome-extension://ponmlkjihgfedcbaponmlkjihgfedcba"},
    )
    assert wrong_origin.status_code == 401

    locked = client.post("/api/auth/lock", headers=headers)
    assert locked.status_code == 200
    after_lock = client.get(
        "/api/browser/matches?url=https%3A%2F%2Fexample.test",
        headers=browser_headers,
    )
    assert after_lock.status_code == 401


def test_pairing_endpoint_does_not_accept_missing_or_reused_code(client: TestClient) -> None:
    headers = _desktop_headers(client)
    issued = client.post("/api/browser/pairing-code", headers=headers)
    code = issued.json()["pairing_code"]
    request_headers = {"Origin": ORIGIN, "X-Vault-Browser-Pairing": code}
    assert client.post("/api/browser/pair", headers=request_headers, json={}).status_code == 200
    assert client.post("/api/browser/pair", headers=request_headers, json={}).status_code == 401
    assert client.post("/api/browser/pair", headers={"Origin": ORIGIN}, json={}).status_code == 403

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("fastapi")

from vault_unified.api.app import create_app

BOOTSTRAP_SECRET = "test-bootstrap-secret-0123456789abcdef"


@pytest.fixture
def client(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        vault_file = Path(tmp) / "secrets.vault"
        monkeypatch.setenv("VAULT_FILE", str(vault_file))
        monkeypatch.setattr("vault_unified.config.get_vault_path", lambda: vault_file)
        app = create_app(
            bootstrap_secret=BOOTSTRAP_SECRET,
            instance_id="test-api-entries",
        )
        with TestClient(app) as test_client:
            yield test_client


def bootstrap_headers() -> dict[str, str]:
    return {"X-Vault-Bootstrap": BOOTSTRAP_SECRET}


def test_unlock_and_crud(client):
    res = client.post(
        "/api/auth/unlock",
        json={"password": "test123", "remember": False},
        headers=bootstrap_headers(),
    )
    assert res.status_code == 200
    token = res.json()["token"]
    headers = {
        **bootstrap_headers(),
        "Authorization": f"Bearer {token}",
    }

    create = client.post(
        "/api/entries",
        json={"title": "GitHub", "username": "u", "password": "p"},
        headers=headers,
    )
    assert create.status_code == 200
    entry_id = create.json()["id"]

    listing = client.get("/api/entries", headers=headers)
    assert listing.status_code == 200
    assert len(listing.json()) == 1

    patch = client.patch(
        f"/api/entries/{entry_id}",
        json={"username": "new"},
        headers=headers,
    )
    assert patch.status_code == 200
    assert patch.json()["username"] == "new"

    delete = client.delete(f"/api/entries/{entry_id}", headers=headers)
    assert delete.status_code == 200

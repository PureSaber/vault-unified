from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("fastapi")

from vault_unified.api.app import create_app
from vault_unified.manager import UnifiedVault

BOOTSTRAP_SECRET = "test-bootstrap-secret-0123456789abcdef"


@pytest.fixture
def client(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        vault_file = Path(tmp) / "secrets.vault"
        monkeypatch.setenv("VAULT_FILE", str(vault_file))
        monkeypatch.setattr("vault_unified.config.get_vault_path", lambda: vault_file)
        UnifiedVault.create(vault_file, "test123")
        app = create_app(
            bootstrap_secret=BOOTSTRAP_SECRET,
            instance_id="test-api-entries",
        )
        with TestClient(app) as test_client:
            yield test_client


def bootstrap_headers() -> dict[str, str]:
    return {"X-Vault-Bootstrap": BOOTSTRAP_SECRET}


def unlock_headers(client: TestClient) -> dict[str, str]:
    res = client.post(
        "/api/auth/unlock",
        json={"password": "test123", "remember": False},
        headers=bootstrap_headers(),
    )
    assert res.status_code == 200
    return {
        **bootstrap_headers(),
        "Authorization": f"Bearer {res.json()['token']}",
    }


def test_unlock_and_crud(client):
    headers = unlock_headers(client)

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

    after_delete = client.get("/api/entries", headers=headers)
    assert after_delete.status_code == 200
    assert after_delete.json() == []


def test_list_returns_presence_flags_without_mask_placeholders(client):
    headers = unlock_headers(client)
    create = client.post(
        "/api/entries",
        json={
            "title": "Mail",
            "password": "actual-password",
            "notes": "private notes",
        },
        headers=headers,
    )
    assert create.status_code == 200
    entry_id = create.json()["id"]

    listing = client.get("/api/entries", headers=headers)
    assert listing.status_code == 200
    item = listing.json()[0]
    assert item["password"] == ""
    assert item["notes"] == ""
    assert item["has_password"] is True
    assert item["has_notes"] is True

    revealed = client.get(
        f"/api/entries/{entry_id}?reveal=true",
        headers=headers,
    )
    assert revealed.status_code == 200
    assert revealed.json()["password"] == "actual-password"
    assert revealed.json()["notes"] == "private notes"


def test_patch_accepts_mask_like_values_and_explicit_empty_strings(client):
    headers = unlock_headers(client)
    create = client.post(
        "/api/entries",
        json={"title": "Example", "password": "old", "notes": "old notes"},
        headers=headers,
    )
    assert create.status_code == 200
    entry_id = create.json()["id"]

    literal_password = "prefix****suffix"
    literal_notes = "•• literal note"
    update = client.patch(
        f"/api/entries/{entry_id}",
        json={"password": literal_password, "notes": literal_notes},
        headers=headers,
    )
    assert update.status_code == 200
    assert update.json()["password"] == literal_password
    assert update.json()["notes"] == literal_notes

    clear = client.patch(
        f"/api/entries/{entry_id}",
        json={"password": "", "notes": ""},
        headers=headers,
    )
    assert clear.status_code == 200
    assert clear.json()["password"] == ""
    assert clear.json()["notes"] == ""
    assert clear.json()["has_password"] is False
    assert clear.json()["has_notes"] is False


def test_invalid_personal_extension_does_not_partially_persist_entry_changes(client):
    headers = unlock_headers(client)
    rejected_create = client.post(
        "/api/entries",
        json={
            "title": "Invalid extension",
            "custom_fields": [{"label": "", "value": "x", "concealed": False}],
        },
        headers=headers,
    )
    assert rejected_create.status_code == 400
    assert client.get("/api/entries", headers=headers).json() == []

    created = client.post(
        "/api/entries",
        json={"title": "Original", "username": "before", "password": "secret"},
        headers=headers,
    )
    assert created.status_code == 200
    rejected_patch = client.patch(
        f"/api/entries/{created.json()['id']}",
        json={
            "title": "Should not save",
            "custom_fields": [{"label": "", "value": "x", "concealed": False}],
        },
        headers=headers,
    )
    assert rejected_patch.status_code == 400
    unchanged = client.get(f"/api/entries/{created.json()['id']}?reveal=true", headers=headers)
    assert unchanged.status_code == 200
    assert unchanged.json()["title"] == "Original"
    assert unchanged.json()["username"] == "before"

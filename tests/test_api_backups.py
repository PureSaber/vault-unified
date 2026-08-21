from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("fastapi")

from vault_unified import backup_manager
from vault_unified.api.app import create_app
from vault_unified.manager import UnifiedVault
from vault_unified.session import sessions

BOOTSTRAP_SECRET = "backup-api-secret-0123456789abcdef"


@pytest.fixture
def backup_api(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        vault_file = root / "active" / "secrets.vault"
        catalog = root / "config" / "backup_catalog.json"
        default_dir = root / "manual"
        monkeypatch.setenv("VAULT_FILE", str(vault_file))
        monkeypatch.setattr(backup_manager, "backup_catalog_path", lambda: catalog)
        monkeypatch.setattr(backup_manager, "default_backup_dir", lambda: default_dir)
        UnifiedVault.create(vault_file, "backup-password")
        sessions._sessions.clear()
        app = create_app(
            bootstrap_secret=BOOTSTRAP_SECRET,
            instance_id="backup-api-test",
        )
        with TestClient(app) as client:
            unlock = client.post(
                "/api/auth/unlock",
                json={"password": "backup-password", "remember": False},
                headers={"X-Vault-Bootstrap": BOOTSTRAP_SECRET},
            )
            assert unlock.status_code == 200
            headers = {
                "X-Vault-Bootstrap": BOOTSTRAP_SECRET,
                "Authorization": f"Bearer {unlock.json()['token']}",
            }
            yield client, headers, vault_file, root
        sessions._sessions.clear()


def test_create_list_pin_and_dry_run_cleanup(backup_api) -> None:
    client, headers, _, root = backup_api
    created_entry = client.post(
        "/api/entries",
        json={"title": "GitHub", "password": "secret"},
        headers=headers,
    )
    assert created_entry.status_code == 200

    destination = root / "off-disk"
    created = client.post(
        "/api/backups/create",
        json={"destination_dir": str(destination)},
        headers=headers,
    )
    assert created.status_code == 200
    manual = created.json()["created"]
    assert manual["kind"] == "manual"
    assert manual["verified"] is True
    assert Path(manual["path"]).is_file()

    listing = client.get("/api/backups", headers=headers)
    assert listing.status_code == 200
    assert listing.json()["count"] >= 2
    assert listing.json()["verified_count"] == listing.json()["count"]

    pinned = client.put(
        "/api/backups/pin",
        json={"path": manual["path"], "pinned": True},
        headers=headers,
    )
    assert pinned.status_code == 200
    assert pinned.json()["backup"]["pinned"] is True

    preview = client.post(
        "/api/backups/prune",
        json={
            "apply": False,
            "newest_count": 0,
            "daily_days": 0,
            "weekly_weeks": 0,
        },
        headers=headers,
    )
    assert preview.status_code == 200
    body = preview.json()
    assert body["applied"] is False
    assert body["deleted_count"] == 0
    assert all(Path(item["path"]).exists() for item in body["delete"])
    assert manual["path"] not in {item["path"] for item in body["delete"]}


def test_restore_requires_confirmation_and_invalidates_session(backup_api) -> None:
    client, headers, _, root = backup_api
    first = client.post(
        "/api/entries",
        json={"title": "Before", "password": "old"},
        headers=headers,
    )
    assert first.status_code == 200
    backup = client.post(
        "/api/backups/create",
        json={"destination_dir": str(root / "restore-source")},
        headers=headers,
    ).json()["created"]
    second = client.post(
        "/api/entries",
        json={"title": "After", "password": "new"},
        headers=headers,
    )
    assert second.status_code == 200

    missing_confirmation = client.post(
        "/api/backups/restore",
        json={
            "path": backup["path"],
            "password": "backup-password",
            "confirm_restore": False,
        },
        headers=headers,
    )
    assert missing_confirmation.status_code == 400

    wrong_password = client.post(
        "/api/backups/restore",
        json={
            "path": backup["path"],
            "password": "wrong-password",
            "confirm_restore": True,
        },
        headers=headers,
    )
    assert wrong_password.status_code == 400
    still_unlocked = client.get("/api/entries", headers=headers)
    assert still_unlocked.status_code == 200
    assert {item["title"] for item in still_unlocked.json()} == {"Before", "After"}

    restored = client.post(
        "/api/backups/restore",
        json={
            "path": backup["path"],
            "password": "backup-password",
            "confirm_restore": True,
        },
        headers=headers,
    )
    assert restored.status_code == 200
    assert restored.json()["locked"] is True

    expired = client.get("/api/entries", headers=headers)
    assert expired.status_code == 401

    unlock = client.post(
        "/api/auth/unlock",
        json={"password": "backup-password", "remember": False},
        headers={"X-Vault-Bootstrap": BOOTSTRAP_SECRET},
    )
    assert unlock.status_code == 200
    restored_headers = {
        "X-Vault-Bootstrap": BOOTSTRAP_SECRET,
        "Authorization": f"Bearer {unlock.json()['token']}",
    }
    listing = client.get("/api/entries", headers=restored_headers)
    assert listing.status_code == 200
    assert [item["title"] for item in listing.json()] == ["Before"]

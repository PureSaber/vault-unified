from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("fastapi")

from vault_unified import backup_manager
from vault_unified.api.app import create_app
from vault_unified.backup_preview import backup_preview_store
from vault_unified.restore_preview import restore_preview_store
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
        from vault_unified import personal_settings

        monkeypatch.setattr(
            personal_settings,
            "personal_settings_path",
            lambda: root / "config" / "personal_settings.json",
        )
        monkeypatch.setattr(
            personal_settings,
            "backup_health_path",
            lambda: root / "config" / "backup_health.v1.json",
        )
        UnifiedVault.create(vault_file, "backup-password")
        sessions._sessions.clear()
        backup_preview_store._intents.clear()
        restore_preview_store._intents.clear()
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
        backup_preview_store._intents.clear()
        restore_preview_store._intents.clear()


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
    assert len(body["preview_token"]) >= 32
    assert body["expires_at"]
    assert all(Path(item["path"]).exists() for item in body["delete"])
    assert manual["path"] not in {item["path"] for item in body["delete"]}


def test_cleanup_apply_requires_and_consumes_exact_preview(backup_api) -> None:
    client, headers, vault_file, _ = backup_api
    for title in ("One", "Two"):
        created = client.post(
            "/api/entries",
            json={"title": title, "password": "synthetic"},
            headers=headers,
        )
        assert created.status_code == 200

    policy = {
        "newest_count": 0,
        "daily_days": 0,
        "weekly_weeks": 0,
    }
    preview = client.post(
        "/api/backups/prune",
        json={"apply": False, **policy},
        headers=headers,
    )
    assert preview.status_code == 200
    plan = preview.json()
    approved_paths = {Path(item["path"]).resolve() for item in plan["delete"]}
    assert approved_paths

    missing_token = client.post(
        "/api/backups/prune",
        json={"apply": True, **policy},
        headers=headers,
    )
    assert missing_token.status_code == 409
    assert all(path.exists() for path in approved_paths)

    changed_after_preview = client.post(
        "/api/entries",
        json={"title": "After preview", "password": "synthetic"},
        headers=headers,
    )
    assert changed_after_preview.status_code == 200
    current_atomic = {
        path.resolve()
        for path, _transaction_id in backup_manager._atomic_backup_candidates(
            vault_file
        )
    }
    new_paths = current_atomic - approved_paths
    assert new_paths

    applied = client.post(
        "/api/backups/prune",
        json={
            "apply": True,
            "preview_token": plan["preview_token"],
            **policy,
        },
        headers=headers,
    )
    assert applied.status_code == 200
    result = applied.json()
    assert result["deleted_count"] == len(approved_paths)
    assert all(not path.exists() for path in approved_paths)
    assert all(path.exists() for path in new_paths)

    replay = client.post(
        "/api/backups/prune",
        json={
            "apply": True,
            "preview_token": plan["preview_token"],
            **policy,
        },
        headers=headers,
    )
    assert replay.status_code == 409


def test_restore_requires_fresh_preview_and_invalidates_session(backup_api) -> None:
    client, headers, vault_file, root = backup_api
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

    legacy_direct_apply = client.post(
        "/api/backups/restore",
        json={
            "path": backup["path"],
            "password": "backup-password",
            "confirm_restore": False,
        },
        headers=headers,
    )
    assert legacy_direct_apply.status_code == 409

    before_failed_preview = vault_file.read_bytes()
    wrong_password = client.post(
        "/api/backups/restore/preview",
        json={"path": backup["path"], "password": "wrong-password"},
        headers=headers,
    )
    assert wrong_password.status_code == 400
    assert vault_file.read_bytes() == before_failed_preview

    preview = client.post(
        "/api/backups/restore/preview",
        json={"path": backup["path"], "password": "backup-password"},
        headers=headers,
    )
    assert preview.status_code == 200
    plan = preview.json()
    assert plan["backup"]["path"] == backup["path"]
    assert "preview" in plan["warning"].lower()
    assert vault_file.read_bytes() == before_failed_preview

    missing_confirmation = client.post(
        "/api/backups/restore/apply",
        json={
            "preview_token": plan["preview_token"],
            "password": "wrong-password",
            "confirm_restore": False,
        },
        headers=headers,
    )
    assert missing_confirmation.status_code == 400
    assert vault_file.read_bytes() == before_failed_preview
    cancelled = client.post(
        "/api/backups/restore/cancel",
        json={"preview_token": plan["preview_token"]},
        headers=headers,
    )
    assert cancelled.status_code == 200
    replay_cancelled = client.post(
        "/api/backups/restore/apply",
        json={
            "preview_token": plan["preview_token"],
            "password": "backup-password",
            "confirm_restore": True,
        },
        headers=headers,
    )
    assert replay_cancelled.status_code == 409
    assert vault_file.read_bytes() == before_failed_preview

    preview = client.post(
        "/api/backups/restore/preview",
        json={"path": backup["path"], "password": "backup-password"},
        headers=headers,
    ).json()
    changed = client.post(
        "/api/entries",
        json={"title": "Changed after preview", "password": "synthetic"},
        headers=headers,
    )
    assert changed.status_code == 200
    stale = client.post(
        "/api/backups/restore/apply",
        json={
            "preview_token": preview["preview_token"],
            "password": "backup-password",
            "confirm_restore": True,
        },
        headers=headers,
    )
    assert stale.status_code == 409
    still_unlocked = client.get("/api/entries", headers=headers)
    assert still_unlocked.status_code == 200
    assert {item["title"] for item in still_unlocked.json()} == {
        "Before",
        "After",
        "Changed after preview",
    }

    preview = client.post(
        "/api/backups/restore/preview",
        json={"path": backup["path"], "password": "backup-password"},
        headers=headers,
    ).json()
    restored = client.post(
        "/api/backups/restore/apply",
        json={
            "preview_token": preview["preview_token"],
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


def test_destination_probe_and_backup_verification_do_not_change_vault(backup_api) -> None:
    client, headers, vault_file, root = backup_api
    destination = root / "existing-backup-folder"
    destination.mkdir()
    before = vault_file.read_bytes()

    probe = client.post(
        "/api/backups/test-destination",
        json={"destination_dir": str(destination)},
        headers=headers,
    )
    assert probe.status_code == 200
    assert probe.json()["exists"] is True
    assert probe.json()["writable"] is True
    assert probe.json()["free_bytes"] > 0
    assert list(destination.iterdir()) == []
    assert vault_file.read_bytes() == before

    created = client.post(
        "/api/backups/create",
        json={"destination_dir": str(destination)},
        headers=headers,
    )
    assert created.status_code == 200
    active_after_backup = vault_file.read_bytes()
    verified = client.post(
        "/api/backups/verify",
        json={"path": created.json()["created"]["path"]},
        headers=headers,
    )
    assert verified.status_code == 200
    assert verified.json()["verified"] is True
    assert vault_file.read_bytes() == active_after_backup

    status = client.get("/api/backups", headers=headers).json()["health"]
    assert status["last_success_at"]
    assert status["last_verification_status"] == "passed"

    Path(created.json()["created"]["path"]).write_bytes(b"generated-invalid-backup")
    before_failed_verification = vault_file.read_bytes()
    failed = client.post(
        "/api/backups/verify",
        json={"path": created.json()["created"]["path"]},
        headers=headers,
    )
    assert failed.status_code == 400
    assert vault_file.read_bytes() == before_failed_verification
    failed_status = client.get("/api/backups", headers=headers).json()["health"]
    assert failed_status["last_verification_status"] == "failed"


def test_automatic_backup_error_persists_until_a_success(backup_api, monkeypatch) -> None:
    client, headers, _, root = backup_api
    configured = client.put(
        "/api/personal/settings",
        json={
            "auto_backup_enabled": True,
            "auto_backup_interval_hours": 24,
            "auto_backup_destination": str(root / "scheduled"),
        },
        headers=headers,
    )
    assert configured.status_code == 200

    from vault_unified import backup_manager, personal_settings

    original = personal_settings.create_manual_backup

    def fail_backup(*args, **kwargs):
        raise OSError("generated failure detail that must not reach persistent status")

    monkeypatch.setattr(personal_settings, "create_manual_backup", fail_backup)
    failed = client.post("/api/personal/maintenance", headers=headers)
    assert failed.status_code == 200
    assert failed.json()["notices"][0]["level"] == "error"
    status = client.get("/api/personal/settings", headers=headers).json()["backup_status"]
    assert status["last_error_summary"] == "Automatic encrypted backup could not be created"
    assert "generated failure" not in status["last_error_summary"]

    monkeypatch.setattr(personal_settings, "create_manual_backup", original)
    succeeded = client.post("/api/personal/maintenance", headers=headers)
    assert succeeded.status_code == 200
    assert succeeded.json()["notices"][0]["level"] == "info"
    cleared = client.get("/api/personal/settings", headers=headers).json()["backup_status"]
    assert cleared["last_success_at"]
    assert cleared["last_error_at"] == ""
    assert cleared["last_error_summary"] == ""


def test_restore_write_failure_keeps_active_vault_bytes(backup_api, monkeypatch) -> None:
    client, headers, vault_file, root = backup_api
    created = client.post(
        "/api/entries",
        json={"title": "Before failure", "password": "generated"},
        headers=headers,
    )
    assert created.status_code == 200
    backup = client.post(
        "/api/backups/create",
        json={"destination_dir": str(root / "restore-failure")},
        headers=headers,
    ).json()["created"]
    client.post(
        "/api/entries",
        json={"title": "Keep current", "password": "generated"},
        headers=headers,
    )
    preview = client.post(
        "/api/backups/restore/preview",
        json={"path": backup["path"], "password": "backup-password"},
        headers=headers,
    ).json()
    before = vault_file.read_bytes()

    def fail_atomic_write(*args, **kwargs):
        raise OSError("generated injected write failure")

    monkeypatch.setattr(backup_manager, "atomic_write_bytes", fail_atomic_write)
    failed = client.post(
        "/api/backups/restore/apply",
        json={
            "preview_token": preview["preview_token"],
            "password": "backup-password",
            "confirm_restore": True,
        },
        headers=headers,
    )
    assert failed.status_code == 400
    assert vault_file.read_bytes() == before
    listing = client.get("/api/entries", headers=headers)
    assert listing.status_code == 200
    assert {entry["title"] for entry in listing.json()} == {
        "Before failure",
        "Keep current",
    }

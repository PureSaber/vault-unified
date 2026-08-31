from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("fastapi")

from vault_unified.api.app import create_app
from vault_unified.manager import UnifiedVault
from vault_unified.recovery_kit import create_recovery_kit
from vault_unified.session import sessions
from vault_unified.restore_preview import restore_preview_store
from vault_unified.vault_format import V3Container, inspect_vault_format_file

BOOTSTRAP_SECRET = "test-bootstrap-secret-0123456789abcdef"


@pytest.fixture
def lifecycle(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        vault_file = root / "active" / "secrets.vault"
        monkeypatch.setenv("VAULT_FILE", str(vault_file))
        monkeypatch.setenv("VAULT_CONFIG_DIR", str(root / "config"))
        sessions._sessions.clear()
        restore_preview_store._intents.clear()
        app = create_app(
            bootstrap_secret=BOOTSTRAP_SECRET,
            instance_id="test-vault-lifecycle",
        )
        with TestClient(app) as client:
            yield client, root, vault_file
        sessions._sessions.clear()
        restore_preview_store._intents.clear()


def headers() -> dict[str, str]:
    return {
        "X-Vault-Bootstrap": BOOTSTRAP_SECRET,
        "X-Vault-Client": "vault-unified-desktop",
    }


def test_missing_vault_requires_explicit_create_or_restore(lifecycle) -> None:
    client, _, vault_file = lifecycle

    info = client.get("/api/auth/vault-info", headers=headers())
    assert info.status_code == 200
    assert info.json() == {
        "exists": False,
        "format": "missing",
        "path": str(vault_file.resolve()),
    }

    unlock = client.post(
        "/api/auth/unlock",
        json={"password": "accidental-password", "remember": False},
        headers=headers(),
    )
    assert unlock.status_code == 404
    assert not vault_file.exists()


def test_create_requires_confirmation_and_defaults_to_v3(lifecycle) -> None:
    client, _, vault_file = lifecycle

    mismatch = client.post(
        "/api/auth/create",
        json={
            "password": "correct horse battery staple",
            "confirm_password": "different",
            "remember": False,
        },
        headers=headers(),
    )
    assert mismatch.status_code == 400
    assert not vault_file.exists()

    created = client.post(
        "/api/auth/create",
        json={
            "password": "correct horse battery staple",
            "confirm_password": "correct horse battery staple",
            "remember": False,
        },
        headers=headers(),
    )
    assert created.status_code == 200
    assert created.json()["message"] == "created"
    assert created.json()["token"]
    assert isinstance(inspect_vault_format_file(vault_file), V3Container)

    info = client.get("/api/auth/vault-info", headers=headers())
    assert info.status_code == 200
    assert info.json()["format"] == "v3"

    duplicate = client.post(
        "/api/auth/create",
        json={
            "password": "another password",
            "confirm_password": "another password",
            "remember": False,
        },
        headers=headers(),
    )
    assert duplicate.status_code == 409


def test_restore_validates_then_copies_legacy_backup_byte_for_byte(lifecycle) -> None:
    client, root, vault_file = lifecycle
    backup = root / "backup" / "legacy.vault"
    backup.parent.mkdir(parents=True)
    vault = UnifiedVault.create(backup, "legacy-password")
    vault.add(
        "GitHub",
        "user@example.com",
        "secret",
        auto_push=False,
    )
    expected = backup.read_bytes()

    direct = client.post(
        "/api/auth/restore",
        json={
            "backup_path": str(backup),
            "password": "legacy-password",
            "remember": False,
        },
        headers=headers(),
    )
    assert direct.status_code == 409
    assert not vault_file.exists()

    preview = client.post(
        "/api/auth/restore/preview",
        json={
            "backup_path": str(backup),
            "password": "legacy-password",
            "remember": False,
        },
        headers=headers(),
    )
    assert preview.status_code == 200
    assert not vault_file.exists()
    restored = client.post(
        "/api/auth/restore/apply",
        json={
            "preview_token": preview.json()["preview_token"],
            "password": "legacy-password",
            "remember": False,
            "confirm_restore": True,
        },
        headers=headers(),
    )
    assert restored.status_code == 200
    assert restored.json()["locked"] is True
    assert vault_file.read_bytes() == expected
    assert not isinstance(inspect_vault_format_file(vault_file), V3Container)

    unlocked = client.post(
        "/api/auth/unlock",
        json={"password": "legacy-password", "remember": False},
        headers=headers(),
    )
    assert unlocked.status_code == 200

    listing = client.get(
        "/api/entries",
        headers={
            **headers(),
            "Authorization": f"Bearer {unlocked.json()['token']}",
        },
    )
    assert listing.status_code == 200
    assert listing.json()[0]["title"] == "GitHub"


def test_restore_wrong_password_leaves_target_absent(lifecycle) -> None:
    client, root, vault_file = lifecycle
    backup = root / "backup.vault"
    UnifiedVault.create(backup, "right-password")

    restored = client.post(
        "/api/auth/restore/preview",
        json={
            "backup_path": str(backup),
            "password": "wrong-password",
            "remember": False,
        },
        headers=headers(),
    )
    assert restored.status_code == 401
    assert not vault_file.exists()


def test_cancelled_startup_restore_preview_cannot_be_applied(lifecycle) -> None:
    client, root, vault_file = lifecycle
    backup = root / "cancelled-backup.vault"
    UnifiedVault.create(backup, "generated-password")
    preview = client.post(
        "/api/auth/restore/preview",
        json={
            "backup_path": str(backup),
            "password": "generated-password",
            "remember": False,
        },
        headers=headers(),
    ).json()
    cancelled = client.post(
        "/api/auth/restore/cancel",
        json={"preview_token": preview["preview_token"]},
        headers=headers(),
    )
    assert cancelled.status_code == 200
    replay = client.post(
        "/api/auth/restore/apply",
        json={
            "preview_token": preview["preview_token"],
            "password": "generated-password",
            "remember": False,
            "confirm_restore": True,
        },
        headers=headers(),
    )
    assert replay.status_code == 409
    assert not vault_file.exists()


def test_restore_never_overwrites_an_active_vault(lifecycle) -> None:
    client, root, vault_file = lifecycle
    active = UnifiedVault.create(vault_file, "active-password")
    active.add("Active", password="keep-me", auto_push=False)
    active_bytes = vault_file.read_bytes()

    backup = root / "other.vault"
    UnifiedVault.create(backup, "backup-password")

    restored = client.post(
        "/api/auth/restore/preview",
        json={
            "backup_path": str(backup),
            "password": "backup-password",
            "remember": False,
        },
        headers=headers(),
    )
    assert restored.status_code == 409
    assert vault_file.read_bytes() == active_bytes


def test_recovery_kit_preview_is_read_only_and_stale_apply_is_rejected(lifecycle) -> None:
    client, root, vault_file = lifecycle
    active = UnifiedVault.create(vault_file, "old-password")
    active.add("Before kit", password="generated-secret", auto_push=False)
    code = "VU-RK-" + "r" * 48
    kit = create_recovery_kit(active, code, root / "offline")
    active.add("After kit", password="generated-later", auto_push=False)

    before_preview = vault_file.read_bytes()
    wrong = client.post(
        "/api/auth/recover/preview",
        json={"kit_path": str(kit), "recovery_code": "VU-RK-" + "x" * 48},
        headers=headers(),
    )
    assert wrong.status_code == 400
    assert vault_file.read_bytes() == before_preview

    preview = client.post(
        "/api/auth/recover/preview",
        json={"kit_path": str(kit), "recovery_code": code},
        headers=headers(),
    )
    assert preview.status_code == 200
    assert preview.json()["kit"]["entry_count"] == 1
    assert vault_file.read_bytes() == before_preview

    active.add("Changed after preview", password="generated-change", auto_push=False)
    stale = client.post(
        "/api/auth/recover/apply",
        json={
            "preview_token": preview.json()["preview_token"],
            "recovery_code": code,
            "new_password": "new-password",
            "confirm_new_password": "new-password",
            "confirm_recovery": True,
        },
        headers=headers(),
    )
    assert stale.status_code == 409
    assert UnifiedVault(vault_file, "old-password").get_by_title("Changed after preview")

    preview = client.post(
        "/api/auth/recover/preview",
        json={"kit_path": str(kit), "recovery_code": code},
        headers=headers(),
    ).json()
    restored = client.post(
        "/api/auth/recover/apply",
        json={
            "preview_token": preview["preview_token"],
            "recovery_code": code,
            "new_password": "new-password",
            "confirm_new_password": "new-password",
            "confirm_recovery": True,
        },
        headers=headers(),
    )
    assert restored.status_code == 200
    assert restored.json()["locked"] is True
    recovered = UnifiedVault(vault_file, "new-password")
    assert [entry.title for entry in recovered.list_all()] == ["Before kit"]
    assert any(vault_file.parent.glob(f"{vault_file.name}.bak.*"))

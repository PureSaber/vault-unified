from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("fastapi")

from vault_unified.api.app import create_app
from vault_unified.manager import UnifiedVault
from vault_unified.session import sessions
from vault_unified.vault_format import V3Container, inspect_vault_format_file

BOOTSTRAP_SECRET = "test-bootstrap-secret-0123456789abcdef"


@pytest.fixture
def lifecycle(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        vault_file = root / "active" / "secrets.vault"
        monkeypatch.setenv("VAULT_FILE", str(vault_file))
        sessions._sessions.clear()
        app = create_app(
            bootstrap_secret=BOOTSTRAP_SECRET,
            instance_id="test-vault-lifecycle",
        )
        with TestClient(app) as client:
            yield client, root, vault_file
        sessions._sessions.clear()


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

    restored = client.post(
        "/api/auth/restore",
        json={
            "backup_path": str(backup),
            "password": "legacy-password",
            "remember": False,
        },
        headers=headers(),
    )
    assert restored.status_code == 200
    assert restored.json()["message"] == "restored"
    assert vault_file.read_bytes() == expected
    assert not isinstance(inspect_vault_format_file(vault_file), V3Container)

    listing = client.get(
        "/api/entries",
        headers={
            **headers(),
            "Authorization": f"Bearer {restored.json()['token']}",
        },
    )
    assert listing.status_code == 200
    assert listing.json()[0]["title"] == "GitHub"


def test_restore_wrong_password_leaves_target_absent(lifecycle) -> None:
    client, root, vault_file = lifecycle
    backup = root / "backup.vault"
    UnifiedVault.create(backup, "right-password")

    restored = client.post(
        "/api/auth/restore",
        json={
            "backup_path": str(backup),
            "password": "wrong-password",
            "remember": False,
        },
        headers=headers(),
    )
    assert restored.status_code == 401
    assert not vault_file.exists()


def test_restore_never_overwrites_an_active_vault(lifecycle) -> None:
    client, root, vault_file = lifecycle
    active = UnifiedVault.create(vault_file, "active-password")
    active.add("Active", password="keep-me", auto_push=False)
    active_bytes = vault_file.read_bytes()

    backup = root / "other.vault"
    UnifiedVault.create(backup, "backup-password")

    restored = client.post(
        "/api/auth/restore",
        json={
            "backup_path": str(backup),
            "password": "backup-password",
            "remember": False,
        },
        headers=headers(),
    )
    assert restored.status_code == 409
    assert vault_file.read_bytes() == active_bytes

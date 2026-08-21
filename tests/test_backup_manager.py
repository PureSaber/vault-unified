from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from vault_unified import backup_manager
from vault_unified.backup_manager import (
    apply_retention_plan,
    create_manual_backup,
    list_backups,
    restore_backup,
    retention_plan,
    set_backup_pinned,
)
from vault_unified.manager import UnifiedVault


def configure_catalog(monkeypatch, root: Path) -> tuple[Path, Path]:
    catalog = root / "config" / "backup_catalog.json"
    manual = root / "manual-backups"
    monkeypatch.setattr(backup_manager, "backup_catalog_path", lambda: catalog)
    monkeypatch.setattr(backup_manager, "default_backup_dir", lambda: manual)
    return catalog, manual


def test_manual_backup_is_exact_encrypted_copy_and_can_be_pinned(monkeypatch, tmp_path) -> None:
    _, manual_dir = configure_catalog(monkeypatch, tmp_path)
    vault_path = tmp_path / "vault" / "secrets.vault"
    vault = UnifiedVault.create(vault_path, "backup-password")
    vault.add("GitHub", "user", "secret", auto_push=False)
    active_bytes = vault_path.read_bytes()

    created = create_manual_backup(vault_path, vault.local.credential)

    created_path = Path(created.path)
    assert created_path.parent == manual_dir.resolve()
    assert created_path.read_bytes() == active_bytes
    assert created.kind == "manual"
    assert created.verified is True
    assert created.pinned is False

    records = list_backups(vault_path, vault.local.credential)
    assert created.path in {record.path for record in records}
    pinned = set_backup_pinned(
        vault_path,
        created.path,
        vault.local.credential,
        True,
    )
    assert pinned.pinned is True
    assert next(
        record for record in list_backups(vault_path, vault.local.credential)
        if record.path == created.path
    ).pinned is True


def test_retention_never_selects_manual_pinned_or_unverified_backups(
    monkeypatch, tmp_path
) -> None:
    configure_catalog(monkeypatch, tmp_path)
    vault_path = tmp_path / "secrets.vault"
    vault = UnifiedVault.create(vault_path, "retention-password")
    vault.add("Initial", password="secret", auto_push=False)
    valid_bytes = vault_path.read_bytes()
    now = datetime.now(timezone.utc)

    generated: list[Path] = []
    for index in range(5):
        path = vault_path.with_name(f"{vault_path.name}.bak.{uuid4().hex}")
        path.write_bytes(valid_bytes)
        timestamp = (now - timedelta(days=60 + index)).timestamp()
        os.utime(path, (timestamp, timestamp))
        generated.append(path.resolve())

    corrupted = vault_path.with_name(f"{vault_path.name}.bak.{uuid4().hex}")
    corrupted.write_bytes(b"not-an-encrypted-vault")
    os.utime(corrupted, ((now - timedelta(days=90)).timestamp(),) * 2)

    manual = create_manual_backup(
        vault_path,
        vault.local.credential,
        tmp_path / "off-disk",
    )
    pinned_path = generated[0]
    set_backup_pinned(
        vault_path,
        pinned_path,
        vault.local.credential,
        True,
    )

    plan = retention_plan(
        vault_path,
        vault.local.credential,
        newest_count=0,
        daily_days=0,
        weekly_weeks=0,
        now=now + timedelta(days=1),
    )
    candidates = {Path(item["path"]).resolve() for item in plan["delete"]}

    assert pinned_path not in candidates
    assert corrupted.resolve() not in candidates
    assert Path(manual.path).resolve() not in candidates
    assert set(generated[1:]).issubset(candidates)
    assert all(path.exists() for path in candidates)

    result = apply_retention_plan(
        vault_path,
        vault.local.credential,
        newest_count=0,
        daily_days=0,
        weekly_weeks=0,
    )
    assert result["errors"] == []
    assert result["deleted_count"] >= len(generated) - 1
    assert pinned_path.exists()
    assert corrupted.exists()
    assert Path(manual.path).exists()
    assert all(not path.exists() for path in generated[1:])


def test_restore_reopens_old_state_and_retains_replaced_active_bytes(
    monkeypatch, tmp_path
) -> None:
    configure_catalog(monkeypatch, tmp_path)
    vault_path = tmp_path / "secrets.vault"
    password = "restore-password"
    vault = UnifiedVault.create(vault_path, password)
    vault.add("Before", username="old", password="old-secret", auto_push=False)
    backup = create_manual_backup(vault_path, vault.local.credential)

    vault.edit(
        "Before",
        username="new",
        password="new-secret",
        auto_push=False,
    )
    vault.add("After", password="second", auto_push=False)
    replaced_active_bytes = vault_path.read_bytes()

    restore_backup(vault_path, backup.path, password)

    reopened = UnifiedVault(vault_path, password)
    entries = reopened.list_all()
    assert [entry.title for entry in entries] == ["Before"]
    assert entries[0].username == "old"
    assert entries[0].password == "old-secret"

    retained = list(vault_path.parent.glob(f"{vault_path.name}.bak.*"))
    assert any(path.read_bytes() == replaced_active_bytes for path in retained)

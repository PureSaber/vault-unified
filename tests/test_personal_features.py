from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from vault_unified.manager import UnifiedVault
from vault_unified.personal_data import (
    add_attachment,
    get_attachment,
    list_history,
    record_history,
    restore_history,
    update_data,
)
from vault_unified.personal_settings import (
    BackupStatus,
    PersonalSettings,
    load_backup_status,
    maybe_create_scheduled_backup,
    save_backup_status,
    save_personal_settings,
)
from vault_unified.recovery_kit import create_recovery_kit, restore_from_recovery_kit
from vault_unified.transfer import export_transfer, import_entries, parse_transfer


def test_personal_metadata_attachment_history_and_restore(tmp_path: Path) -> None:
    vault = UnifiedVault.create(tmp_path / "secrets.vault", "test-password")
    entry = vault.add("GitHub", password="first", auto_push=False)
    update_data(
        entry,
        entry_type="ssh_key",
        custom_fields=[{"label": "Fingerprint", "value": "SHA256:example", "concealed": False}],
        totp_secret="JBSWY3DPEHPK3PXP",
    )
    attachment = add_attachment(
        entry,
        filename="id_ed25519.pub",
        mime_type="text/plain",
        data_b64=base64.b64encode(b"ssh-ed25519 AAAA").decode("ascii"),
    )
    vault.local.replace_entry(entry)
    record_history(entry)
    entry.password = "second"
    vault.local.replace_entry(entry)

    history = list_history(entry, reveal=False)
    assert history[0]["snapshot"]["password"] == ""
    assert history[0]["snapshot"]["totp_secret"] == ""
    restore_history(entry, history[0]["id"])
    assert entry.password == "first"
    assert get_attachment(entry, attachment["id"])["data_b64"]


def test_transfer_json_round_trip_preserves_personal_fields(tmp_path: Path) -> None:
    source = UnifiedVault.create(tmp_path / "source.vault", "source-password")
    entry = source.add("Bank", username="me", password="secret", auto_push=False)
    update_data(
        entry,
        entry_type="card",
        custom_fields=[{"label": "Last four", "value": "1234", "concealed": True}],
    )
    source.local.replace_entry(entry)
    content, _, _ = export_transfer(source, "json")

    destination = UnifiedVault.create(tmp_path / "destination.vault", "destination-password")
    result = import_entries(destination, parse_transfer(content, "json"))
    assert result == {"imported": 1}
    imported = destination.get_by_title("Bank")
    assert imported is not None
    assert imported.source_metadata["vault_unified:personal"]["entry_type"] == "card"


def test_scheduled_backup_creates_verified_copy_when_due(tmp_path: Path, monkeypatch) -> None:
    from vault_unified import backup_manager, personal_settings

    settings_path = tmp_path / "config" / "personal_settings.json"
    monkeypatch.setattr(personal_settings, "personal_settings_path", lambda: settings_path)
    monkeypatch.setattr(
        personal_settings,
        "backup_health_path",
        lambda: tmp_path / "config" / "backup_health.v1.json",
    )
    monkeypatch.setattr(backup_manager, "backup_catalog_path", lambda: tmp_path / "config" / "backup_catalog.json")
    vault = UnifiedVault.create(tmp_path / "active" / "secrets.vault", "backup-password")
    vault.add("Mail", password="secret", auto_push=False)
    remote_dir = tmp_path / "synced-folder"
    save_personal_settings(
        PersonalSettings(
            auto_backup_enabled=True,
            auto_backup_interval_hours=24,
            auto_backup_destination=str(remote_dir),
        )
    )
    record = maybe_create_scheduled_backup(vault, now=datetime.now(timezone.utc))
    assert record is not None
    assert Path(record.path).is_file()
    assert record.verified is True
    assert maybe_create_scheduled_backup(vault, now=datetime.now(timezone.utc)) is None


def test_personal_settings_accept_old_files_without_backup_status() -> None:
    old = {
        "version": 1,
        "lock_after_seconds": 900,
        "auto_backup_enabled": False,
        "auto_backup_interval_hours": 24,
        "auto_backup_destination": "",
        "last_auto_backup_at": "",
    }
    parsed = PersonalSettings.from_dict(old)
    assert parsed.backup_status == BackupStatus().to_dict()
    assert PersonalSettings.from_dict(parsed.to_dict()).to_dict() == parsed.to_dict()


def test_backup_health_uses_optional_namespaced_sidecar(tmp_path: Path, monkeypatch) -> None:
    from vault_unified import personal_settings

    settings_path = tmp_path / "config" / "personal_settings.json"
    health_path = tmp_path / "config" / "backup_health.v1.json"
    monkeypatch.setattr(personal_settings, "personal_settings_path", lambda: settings_path)
    monkeypatch.setattr(personal_settings, "backup_health_path", lambda: health_path)

    settings = PersonalSettings()
    settings.backup_status = BackupStatus(last_success_at="2026-01-02T03:04:05+00:00").to_dict()
    save_personal_settings(settings)
    save_backup_status(settings.backup_status)

    stored_settings = json.loads(settings_path.read_text(encoding="utf-8"))
    stored_health = json.loads(health_path.read_text(encoding="utf-8"))
    assert "backup_status" not in stored_settings
    assert stored_health["namespace"] == "vault_unified.backup_health"
    assert load_backup_status().last_success_at == "2026-01-02T03:04:05+00:00"


def test_recovery_kit_restores_entries_under_a_new_password(tmp_path: Path) -> None:
    active = tmp_path / "active" / "secrets.vault"
    vault = UnifiedVault.create(active, "old-password")
    vault.add("Recovery test", password="saved-secret", auto_push=False)
    code = "VU-RK-" + "x" * 48
    kit = create_recovery_kit(vault, code, tmp_path / "offline")

    vault.add("Later edit", password="will-disappear", auto_push=False)
    restore_from_recovery_kit(active, kit, code, "new-password")
    restored = UnifiedVault(active, "new-password")
    assert [entry.title for entry in restored.list_all()] == ["Recovery test"]


def test_recovery_kit_cannot_overwrite_target_that_appeared_after_preview(tmp_path: Path) -> None:
    source = UnifiedVault.create(tmp_path / "source.vault", "source-password")
    source.add("Generated entry", password="generated-secret", auto_push=False)
    code = "VU-RK-" + "z" * 48
    kit = create_recovery_kit(source, code, tmp_path / "offline")
    target = tmp_path / "new-active.vault"
    appeared = UnifiedVault.create(target, "appeared-password")
    appeared.add("Do not replace", password="generated-later", auto_push=False)
    before = target.read_bytes()

    with pytest.raises(FileExistsError):
        restore_from_recovery_kit(
            target,
            kit,
            code,
            "new-password",
            expected_target_sha256="",
        )

    assert target.read_bytes() == before

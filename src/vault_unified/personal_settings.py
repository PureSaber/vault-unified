"""Non-secret preferences for the personal desktop experience."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from vault_unified.backup_manager import BackupRecord, create_manual_backup
from vault_unified.config import get_config_dir
from vault_unified.storage import atomic_write_bytes, require_clean_storage


PERSONAL_SETTINGS_VERSION = 1
MIN_LOCK_SECONDS = 60
MAX_LOCK_SECONDS = 60 * 60
MIN_BACKUP_INTERVAL_HOURS = 1
MAX_BACKUP_INTERVAL_HOURS = 24 * 30


@dataclass
class PersonalSettings:
    version: int = PERSONAL_SETTINGS_VERSION
    lock_after_seconds: int = 15 * 60
    auto_backup_enabled: bool = False
    auto_backup_interval_hours: int = 24
    auto_backup_destination: str = ""
    last_auto_backup_at: str = ""

    @classmethod
    def from_dict(cls, value: object) -> "PersonalSettings":
        if value in (None, {}):
            return cls()
        if not isinstance(value, dict) or set(value) != set(asdict(cls())):
            raise ValueError("Personal settings have an unsupported schema")
        if value.get("version") != PERSONAL_SETTINGS_VERSION:
            raise ValueError("Personal settings have an unsupported version")
        lock_after = value.get("lock_after_seconds")
        interval = value.get("auto_backup_interval_hours")
        enabled = value.get("auto_backup_enabled")
        destination = value.get("auto_backup_destination")
        last_backup = value.get("last_auto_backup_at")
        if (
            isinstance(lock_after, bool)
            or not isinstance(lock_after, int)
            or not MIN_LOCK_SECONDS <= lock_after <= MAX_LOCK_SECONDS
        ):
            raise ValueError("Lock timeout is outside the supported range")
        if (
            isinstance(interval, bool)
            or not isinstance(interval, int)
            or not MIN_BACKUP_INTERVAL_HOURS <= interval <= MAX_BACKUP_INTERVAL_HOURS
        ):
            raise ValueError("Backup interval is outside the supported range")
        if not isinstance(enabled, bool) or not isinstance(destination, str) or not isinstance(last_backup, str):
            raise ValueError("Personal settings contain invalid values")
        if len(destination) > 32768:
            raise ValueError("Backup destination is too long")
        if last_backup:
            try:
                parsed = datetime.fromisoformat(last_backup)
            except ValueError as exc:
                raise ValueError("Last backup time is invalid") from exc
            if parsed.tzinfo is None:
                raise ValueError("Last backup time must include a timezone")
        return cls(
            lock_after_seconds=lock_after,
            auto_backup_enabled=enabled,
            auto_backup_interval_hours=interval,
            auto_backup_destination=destination,
            last_auto_backup_at=last_backup,
        )

    def to_dict(self) -> dict:
        return asdict(self)


def personal_settings_path() -> Path:
    return get_config_dir() / "personal_settings.json"


def load_personal_settings() -> PersonalSettings:
    path = personal_settings_path()
    require_clean_storage(path)
    if not path.exists():
        return PersonalSettings()
    if path.is_symlink() or not path.is_file():
        raise ValueError("Personal settings must be a regular file")
    return PersonalSettings.from_dict(json.loads(path.read_text(encoding="utf-8")))


def save_personal_settings(settings: PersonalSettings) -> PersonalSettings:
    parsed = PersonalSettings.from_dict(settings.to_dict())
    encoded = json.dumps(parsed.to_dict(), indent=2, ensure_ascii=False).encode("utf-8")

    def validate(candidate: bytes) -> None:
        PersonalSettings.from_dict(json.loads(candidate.decode("utf-8")))

    atomic_write_bytes(personal_settings_path(), encoded, validator=validate)
    return parsed


def update_personal_settings(current: PersonalSettings, **changes: object) -> PersonalSettings:
    value = current.to_dict()
    for key, item in changes.items():
        if item is not None:
            value[key] = item
    return PersonalSettings.from_dict(value)


def _backup_due(settings: PersonalSettings, now: datetime) -> bool:
    if not settings.auto_backup_enabled:
        return False
    if not settings.last_auto_backup_at:
        return True
    previous = datetime.fromisoformat(settings.last_auto_backup_at)
    return now >= previous + timedelta(hours=settings.auto_backup_interval_hours)


def maybe_create_scheduled_backup(vault: object, *, now: datetime | None = None) -> BackupRecord | None:
    """Create one verified copy when an enabled schedule is due.

    This is deliberately called only by an authenticated desktop maintenance
    request.  The application never starts a background process that can keep
    a vault unlocked after the user exits.
    """
    settings = load_personal_settings()
    current = now or datetime.now(timezone.utc)
    if not _backup_due(settings, current):
        return None
    destination = settings.auto_backup_destination or None
    record = create_manual_backup(
        vault.vault_path,
        vault.local.credential,
        destination,
    )
    settings.last_auto_backup_at = current.isoformat()
    save_personal_settings(settings)
    return record

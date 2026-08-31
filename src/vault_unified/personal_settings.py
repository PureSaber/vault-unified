"""Non-secret preferences for the personal desktop experience."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from vault_unified.backup_manager import BackupRecord, create_manual_backup
from vault_unified.config import get_config_dir
from vault_unified.storage import atomic_write_bytes, require_clean_storage


PERSONAL_SETTINGS_VERSION = 1
BACKUP_HEALTH_NAMESPACE = "vault_unified.backup_health"
BACKUP_HEALTH_VERSION = 1
MIN_LOCK_SECONDS = 60
MAX_LOCK_SECONDS = 60 * 60
MIN_BACKUP_INTERVAL_HOURS = 1
MAX_BACKUP_INTERVAL_HOURS = 24 * 30
BACKUP_VERIFICATION_STATES = {"unverified", "passed", "failed"}


class ScheduledBackupStatusError(OSError):
    """The encrypted copy exists, but its scheduling metadata did not commit."""

    def __init__(self, record: BackupRecord) -> None:
        super().__init__("Scheduled backup was created but status could not be saved")
        self.record = record


@dataclass
class BackupStatus:
    """Non-secret, optional health metadata for the security center."""

    last_success_at: str = ""
    last_error_at: str = ""
    last_error_summary: str = ""
    last_verification_at: str = ""
    last_verification_status: str = "unverified"
    recovery_kit_created_at: str = ""

    @classmethod
    def from_dict(cls, value: object) -> "BackupStatus":
        if value in (None, {}):
            return cls()
        if not isinstance(value, dict) or set(value) - set(asdict(cls())):
            raise ValueError("Backup status has an unsupported schema")
        parsed = cls(**{**asdict(cls()), **value})
        for name in (
            "last_success_at",
            "last_error_at",
            "last_error_summary",
            "last_verification_at",
            "recovery_kit_created_at",
        ):
            item = getattr(parsed, name)
            if not isinstance(item, str):
                raise ValueError("Backup status contains invalid values")
            if name.endswith("_at") and item:
                try:
                    timestamp = datetime.fromisoformat(item)
                except ValueError as exc:
                    raise ValueError("Backup status time is invalid") from exc
                if timestamp.tzinfo is None:
                    raise ValueError("Backup status time must include a timezone")
        if (
            not isinstance(parsed.last_verification_status, str)
            or parsed.last_verification_status not in BACKUP_VERIFICATION_STATES
        ):
            raise ValueError("Backup verification status is invalid")
        if len(parsed.last_error_summary) > 500:
            raise ValueError("Backup error summary is too long")
        return parsed

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PersonalSettings:
    version: int = PERSONAL_SETTINGS_VERSION
    lock_after_seconds: int = 15 * 60
    auto_backup_enabled: bool = False
    auto_backup_interval_hours: int = 24
    auto_backup_destination: str = ""
    last_auto_backup_at: str = ""
    backup_status: dict = field(default_factory=lambda: BackupStatus().to_dict())

    @classmethod
    def from_dict(cls, value: object) -> "PersonalSettings":
        if value in (None, {}):
            return cls()
        expected = set(asdict(cls()))
        required = expected - {"backup_status"}
        if (
            not isinstance(value, dict)
            or set(value) - expected
            or not required.issubset(value)
        ):
            raise ValueError("Personal settings have an unsupported schema")
        if value.get("version") != PERSONAL_SETTINGS_VERSION:
            raise ValueError("Personal settings have an unsupported version")
        lock_after = value.get("lock_after_seconds")
        interval = value.get("auto_backup_interval_hours")
        enabled = value.get("auto_backup_enabled")
        destination = value.get("auto_backup_destination")
        last_backup = value.get("last_auto_backup_at")
        backup_status = BackupStatus.from_dict(value.get("backup_status"))
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
            backup_status=backup_status.to_dict(),
        )

    def to_dict(self) -> dict:
        return asdict(self)

    def to_storage_dict(self) -> dict:
        """Return the v1.2-compatible settings schema.

        Backup health deliberately lives in a separate optional namespaced
        file.  Older releases strictly reject unknown personal-settings keys,
        so adding health metadata to that file would make rollback unsafe.
        """

        value = asdict(self)
        value.pop("backup_status", None)
        return value


def personal_settings_path() -> Path:
    return get_config_dir() / "personal_settings.json"


def backup_health_path() -> Path:
    return get_config_dir() / "backup_health.v1.json"


def load_backup_status() -> BackupStatus:
    path = backup_health_path()
    require_clean_storage(path)
    if not path.exists():
        return BackupStatus()
    if path.is_symlink() or not path.is_file():
        raise ValueError("Backup health status must be a regular file")
    value = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(value, dict)
        or set(value) != {"namespace", "version", "status"}
        or value.get("namespace") != BACKUP_HEALTH_NAMESPACE
        or value.get("version") != BACKUP_HEALTH_VERSION
    ):
        raise ValueError("Backup health status has an unsupported schema")
    return BackupStatus.from_dict(value.get("status"))


def save_backup_status(status: BackupStatus | dict) -> BackupStatus:
    parsed = status if isinstance(status, BackupStatus) else BackupStatus.from_dict(status)
    payload = {
        "namespace": BACKUP_HEALTH_NAMESPACE,
        "version": BACKUP_HEALTH_VERSION,
        "status": parsed.to_dict(),
    }
    encoded = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")

    def validate(candidate: bytes) -> None:
        value = json.loads(candidate.decode("utf-8"))
        if (
            not isinstance(value, dict)
            or set(value) != {"namespace", "version", "status"}
            or value.get("namespace") != BACKUP_HEALTH_NAMESPACE
            or value.get("version") != BACKUP_HEALTH_VERSION
        ):
            raise ValueError("Backup health status has an unsupported schema")
        BackupStatus.from_dict(value.get("status"))

    atomic_write_bytes(backup_health_path(), encoded, validator=validate)
    return parsed


def load_personal_settings() -> PersonalSettings:
    path = personal_settings_path()
    require_clean_storage(path)
    if not path.exists():
        settings = PersonalSettings()
    else:
        if path.is_symlink() or not path.is_file():
            raise ValueError("Personal settings must be a regular file")
        settings = PersonalSettings.from_dict(json.loads(path.read_text(encoding="utf-8")))
    settings.backup_status = load_backup_status().to_dict()
    return settings


def save_personal_settings(settings: PersonalSettings) -> PersonalSettings:
    parsed = PersonalSettings.from_dict(settings.to_dict())
    encoded = json.dumps(parsed.to_storage_dict(), indent=2, ensure_ascii=False).encode("utf-8")

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


def update_backup_status(
    current: PersonalSettings,
    *,
    last_success_at: str | None = None,
    last_error_at: str | None = None,
    last_error_summary: str | None = None,
    last_verification_at: str | None = None,
    last_verification_status: str | None = None,
    recovery_kit_created_at: str | None = None,
) -> PersonalSettings:
    status = BackupStatus.from_dict(current.backup_status).to_dict()
    changes = {
        "last_success_at": last_success_at,
        "last_error_at": last_error_at,
        "last_error_summary": last_error_summary,
        "last_verification_at": last_verification_at,
        "last_verification_status": last_verification_status,
        "recovery_kit_created_at": recovery_kit_created_at,
    }
    for name, value in changes.items():
        if value is not None:
            status[name] = value
    current.backup_status = BackupStatus.from_dict(status).to_dict()
    return current


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
    completed_at = current.isoformat()
    settings.last_auto_backup_at = completed_at
    update_backup_status(
        settings,
        last_success_at=completed_at,
        last_error_at="",
        last_error_summary="",
    )
    try:
        save_personal_settings(settings)
        save_backup_status(settings.backup_status)
    except (OSError, ValueError) as exc:
        raise ScheduledBackupStatusError(record) from exc
    return record

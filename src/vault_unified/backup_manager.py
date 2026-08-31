from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import secrets
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from vault_unified.config import get_config_dir
from vault_unified.crypto import decrypt_payload
from vault_unified.models import SecretEntry
from vault_unified.storage import atomic_write_bytes, require_clean_storage
from vault_unified.v3_crypto import V3Credential
from vault_unified.vault_format import V3Container, inspect_vault_format_file

CATALOG_VERSION = 1
_ATOMIC_BACKUP_ID = re.compile(r"^[0-9a-f]{32}$")


@dataclass(frozen=True)
class BackupRecord:
    path: str
    kind: str
    size: int
    modified_at: str
    sha256: str
    format: str
    verified: bool
    pinned: bool
    transaction_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "kind": self.kind,
            "size": self.size,
            "modified_at": self.modified_at,
            "sha256": self.sha256,
            "format": self.format,
            "verified": self.verified,
            "pinned": self.pinned,
            "transaction_id": self.transaction_id,
        }


def backup_catalog_path() -> Path:
    return get_config_dir() / "backup_catalog.json"


def default_backup_dir() -> Path:
    return get_config_dir().parent / "backups"


def _canonical(path: str | Path) -> str:
    return str(Path(path).expanduser().resolve())


def _validate_catalog(value: Any) -> dict[str, set[str]]:
    if value in (None, {}):
        return {"pinned": set(), "external": set()}
    if not isinstance(value, dict) or value.get("version") != CATALOG_VERSION:
        raise ValueError("Backup catalog has an unsupported schema")
    result: dict[str, set[str]] = {}
    for key in ("pinned", "external"):
        raw = value.get(key, [])
        if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
            raise ValueError("Backup catalog paths must be a list of strings")
        result[key] = {_canonical(item) for item in raw if item}
    return result


def load_backup_catalog() -> dict[str, set[str]]:
    path = backup_catalog_path()
    require_clean_storage(path)
    if not path.exists():
        return {"pinned": set(), "external": set()}
    if path.is_symlink() or not path.is_file():
        raise ValueError("Backup catalog must be a regular file")
    return _validate_catalog(json.loads(path.read_text(encoding="utf-8")))


def _save_backup_catalog(catalog: dict[str, set[str]]) -> None:
    payload = {
        "version": CATALOG_VERSION,
        "pinned": sorted(catalog["pinned"]),
        "external": sorted(catalog["external"]),
    }
    encoded = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")

    def validate(candidate: bytes) -> None:
        _validate_catalog(json.loads(candidate.decode("utf-8")))

    atomic_write_bytes(backup_catalog_path(), encoded, validator=validate)


def _atomic_backup_candidates(vault_path: Path) -> list[tuple[Path, str]]:
    prefix = f"{vault_path.name}.bak."
    result: list[tuple[Path, str]] = []
    if not vault_path.parent.exists():
        return result
    for candidate in vault_path.parent.glob(f"{vault_path.name}.bak.*"):
        txid = candidate.name[len(prefix) :] if candidate.name.startswith(prefix) else ""
        if _ATOMIC_BACKUP_ID.fullmatch(txid):
            result.append((candidate, txid))
    return result


def _format_name(path: Path) -> str:
    try:
        container = inspect_vault_format_file(path)
        return "v3" if isinstance(container, V3Container) else "legacy"
    except Exception:
        return "unreadable"


def _record(
    path: Path,
    *,
    kind: str,
    pinned: bool,
    credential: V3Credential,
    transaction_id: str = "",
) -> BackupRecord | None:
    if path.is_symlink() or not path.is_file():
        return None
    data = path.read_bytes()
    verified = False
    try:
        decrypt_payload(credential, data)
        verified = True
    except Exception:
        verified = False
    stat = path.stat()
    return BackupRecord(
        path=_canonical(path),
        kind=kind,
        size=len(data),
        modified_at=datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        sha256=hashlib.sha256(data).hexdigest(),
        format=_format_name(path),
        verified=verified,
        pinned=pinned,
        transaction_id=transaction_id,
    )


def list_backups(vault_path: Path, credential: V3Credential) -> list[BackupRecord]:
    vault_path = vault_path.resolve()
    catalog = load_backup_catalog()
    records: list[BackupRecord] = []
    seen: set[str] = set()
    for path, txid in _atomic_backup_candidates(vault_path):
        canonical = _canonical(path)
        record = _record(
            path,
            kind="local_atomic",
            pinned=canonical in catalog["pinned"],
            credential=credential,
            transaction_id=txid,
        )
        if record:
            records.append(record)
            seen.add(canonical)
    for value in catalog["external"]:
        if value in seen:
            continue
        record = _record(
            Path(value),
            kind="manual",
            pinned=value in catalog["pinned"],
            credential=credential,
        )
        if record:
            records.append(record)
    return sorted(records, key=lambda item: item.modified_at, reverse=True)


def create_manual_backup(
    vault_path: Path,
    credential: V3Credential,
    destination_dir: str | Path | None = None,
) -> BackupRecord:
    source = vault_path.resolve()
    if source.is_symlink() or not source.is_file():
        raise FileNotFoundError(f"Active vault not found: {source}")
    data = source.read_bytes()
    decrypt_payload(credential, data)
    destination = Path(destination_dir).expanduser() if destination_dir else default_backup_dir()
    destination = destination.resolve()
    if destination.exists() and (destination.is_symlink() or not destination.is_dir()):
        raise ValueError("Backup destination must be a regular directory")
    destination.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    digest = hashlib.sha256(data).hexdigest()
    path = destination / f"VaultUnified-{stamp}-{digest[:12]}.vault"
    counter = 1
    while path.exists():
        path = destination / f"VaultUnified-{stamp}-{digest[:12]}-{counter}.vault"
        counter += 1
    atomic_write_bytes(
        path,
        data,
        validator=lambda candidate: decrypt_payload(credential, candidate),
        must_not_exist=True,
    )
    catalog = load_backup_catalog()
    canonical = _canonical(path)
    catalog["external"].add(canonical)
    _save_backup_catalog(catalog)
    record = _record(
        path,
        kind="manual",
        pinned=False,
        credential=credential,
    )
    if record is None:  # pragma: no cover - atomic writer guarantees regular file
        raise RuntimeError("Created backup could not be inspected")
    return record


def test_backup_destination(destination_dir: str | Path) -> dict[str, Any]:
    """Probe an existing directory with a short-lived, non-secret file."""

    destination = Path(destination_dir).expanduser().resolve()
    result: dict[str, Any] = {
        "path": str(destination),
        "exists": destination.exists(),
        "writable": False,
        "free_bytes": 0,
    }
    if not destination.exists():
        result["message"] = "Backup folder does not exist"
        return result
    if destination.is_symlink() or not destination.is_dir():
        result["message"] = "Backup destination must be a regular directory"
        return result
    result["free_bytes"] = shutil.disk_usage(destination).free
    probe = destination / f".vault-unified-write-test-{secrets.token_hex(12)}"
    descriptor: int | None = None
    try:
        descriptor = os.open(probe, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.write(descriptor, b"vault-unified generated write test\n")
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        probe.unlink()
        result["writable"] = True
        result["message"] = "Backup folder is writable"
    except OSError:
        result["message"] = "Backup folder is not writable"
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if probe.exists():
            probe.unlink()
    return result


def verify_backup(
    vault_path: Path,
    backup_path: str | Path,
    credential: V3Credential,
) -> BackupRecord:
    """Authenticate and parse a registered backup without changing the vault."""

    canonical = _canonical(backup_path)
    records = {record.path: record for record in list_backups(vault_path, credential)}
    record = records.get(canonical)
    if record is None:
        raise KeyError("Backup is not registered or is not a local atomic backup")
    source = Path(canonical)
    if source.is_symlink() or not source.is_file():
        raise FileNotFoundError("Backup was not found")
    data = source.read_bytes()
    if hashlib.sha256(data).hexdigest() != record.sha256:
        raise ValueError("Backup changed while it was being verified")
    payload = decrypt_payload(credential, data)
    if (
        not isinstance(payload, dict)
        or payload.get("version") not in {1, 2}
        or not isinstance(payload.get("entries"), dict)
    ):
        raise ValueError("Backup payload is not supported")
    for entry_id, entry in payload["entries"].items():
        if not isinstance(entry_id, str) or not isinstance(entry, dict):
            raise ValueError("Backup entry schema is invalid")
        SecretEntry.from_dict(entry)
    return BackupRecord(**{**record.to_dict(), "verified": True})


def set_backup_pinned(
    vault_path: Path,
    backup_path: str | Path,
    credential: V3Credential,
    pinned: bool,
) -> BackupRecord:
    canonical = _canonical(backup_path)
    records = {record.path: record for record in list_backups(vault_path, credential)}
    if canonical not in records:
        raise KeyError("Backup is not registered or is not a local atomic backup")
    catalog = load_backup_catalog()
    if pinned:
        catalog["pinned"].add(canonical)
    else:
        catalog["pinned"].discard(canonical)
    _save_backup_catalog(catalog)
    current = records[canonical]
    return BackupRecord(**{**current.to_dict(), "pinned": pinned})


def retention_plan(
    vault_path: Path,
    credential: V3Credential,
    *,
    newest_count: int = 10,
    daily_days: int = 30,
    weekly_weeks: int = 12,
    now: datetime | None = None,
) -> dict[str, Any]:
    if min(newest_count, daily_days, weekly_weeks) < 0:
        raise ValueError("Retention values must be non-negative")
    current_time = now or datetime.now(timezone.utc)
    records = list_backups(vault_path, credential)
    local = [record for record in records if record.kind == "local_atomic"]
    eligible = [record for record in local if record.verified and not record.pinned]
    keep: set[str] = {
        record.path
        for record in records
        if record.kind != "local_atomic" or record.pinned or not record.verified
    }
    for record in eligible[:newest_count]:
        keep.add(record.path)

    daily_seen: set[str] = set()
    weekly_seen: set[str] = set()
    for record in eligible:
        modified = datetime.fromisoformat(record.modified_at)
        age = current_time - modified
        if age <= timedelta(days=daily_days):
            day = modified.date().isoformat()
            if day not in daily_seen:
                daily_seen.add(day)
                keep.add(record.path)
        if age <= timedelta(weeks=weekly_weeks):
            iso = modified.isocalendar()
            week = f"{iso.year}-W{iso.week:02d}"
            if week not in weekly_seen:
                weekly_seen.add(week)
                keep.add(record.path)

    delete = [record for record in eligible if record.path not in keep]
    return {
        "policy": {
            "newest_count": newest_count,
            "daily_days": daily_days,
            "weekly_weeks": weekly_weeks,
        },
        "keep_count": len(records) - len(delete),
        "delete_count": len(delete),
        "reclaim_bytes": sum(record.size for record in delete),
        "delete": [record.to_dict() for record in delete],
    }


def apply_retention_plan(
    vault_path: Path,
    credential: V3Credential,
    *,
    newest_count: int = 10,
    daily_days: int = 30,
    weekly_weeks: int = 12,
    approved_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if approved_plan is None:
        plan = retention_plan(
            vault_path,
            credential,
            newest_count=newest_count,
            daily_days=daily_days,
            weekly_weeks=weekly_weeks,
        )
    else:
        plan = copy.deepcopy(approved_plan)
        expected_policy = {
            "newest_count": newest_count,
            "daily_days": daily_days,
            "weekly_weeks": weekly_weeks,
        }
        if plan.get("policy") != expected_policy:
            raise ValueError("Backup cleanup policy changed after preview")

    current_records = {
        record.path: record for record in list_backups(vault_path, credential)
    }
    deleted = 0
    reclaimed = 0
    errors: list[str] = []
    for item in plan["delete"]:
        path = Path(item["path"])
        try:
            current = current_records.get(item["path"])
            if current is None:
                raise ValueError("backup is no longer registered")
            if current.kind != "local_atomic" or current.pinned or not current.verified:
                raise ValueError("backup is no longer eligible")
            if current.sha256 != item["sha256"]:
                raise ValueError("backup changed after retention planning")
            if path.is_symlink() or not path.is_file():
                raise ValueError("backup disappeared or changed type")
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != item["sha256"]:
                raise ValueError("backup changed after retention planning")
            decrypt_payload(credential, data)
            path.unlink()
            deleted += 1
            reclaimed += len(data)
        except Exception as exc:
            errors.append(f"{path.name}: {type(exc).__name__}")
    return {
        **plan,
        "applied": True,
        "deleted_count": deleted,
        "reclaimed_bytes": reclaimed,
        "errors": errors,
    }


def restore_backup(
    vault_path: Path,
    backup_path: str | Path,
    credential: V3Credential,
    *,
    expected_active_sha256: str | None = None,
    expected_backup_sha256: str | None = None,
) -> None:
    active = vault_path.resolve()
    canonical = _canonical(backup_path)
    records = {record.path: record for record in list_backups(active, credential)}
    record = records.get(canonical)
    if record is None:
        raise KeyError("Backup is not registered or is not a local atomic backup")
    source = Path(canonical)
    data = source.read_bytes()
    source_digest = hashlib.sha256(data).hexdigest()
    if expected_backup_sha256 is not None and source_digest != expected_backup_sha256:
        raise ValueError("Backup changed after the restore preview")
    decrypt_payload(credential, data)
    if active.is_symlink() or not active.is_file():
        raise FileNotFoundError(f"Active vault not found: {active}")
    expected = hashlib.sha256(active.read_bytes()).hexdigest()
    if expected_active_sha256 is not None and expected != expected_active_sha256:
        raise ValueError("Active vault changed after the restore preview")
    atomic_write_bytes(
        active,
        data,
        validator=lambda candidate: decrypt_payload(credential, candidate),
        expected_old_sha256=expected_active_sha256 or expected,
    )

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from uuid import UUID, uuid4


Validator = Callable[[bytes], None]
FaultHook = Callable[[str], None]

JOURNAL_VERSION = 1
MAX_JOURNAL_BYTES = 16 * 1024
DEFAULT_STALE_LOCK_SECONDS = 10 * 60
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


class StorageError(RuntimeError):
    """Base error for durable local storage operations."""


class StorageBusyError(StorageError):
    """Another writer owns the per-file transaction lock."""


class RecoveryRequiredError(StorageError):
    """An interrupted transaction must be inspected before another write."""

    def __init__(self, path: Path, transaction_ids: tuple[str, ...]) -> None:
        self.path = path
        self.transaction_ids = transaction_ids
        super().__init__(
            f"Storage recovery required for {path} "
            f"(transactions: {', '.join(transaction_ids)})"
        )


class RecoveryAmbiguousError(StorageError):
    """Recovery cannot safely choose one durable candidate."""


class ConcurrentStorageChangeError(StorageError):
    """The live file changed after a caller built its replacement candidate."""


@dataclass(frozen=True)
class AtomicWriteReceipt:
    transaction_id: str
    path: Path
    sha256: str
    backup_path: Path | None


@dataclass(frozen=True)
class RecoveryPlan:
    transaction_id: str
    action: str
    path: Path
    journal_path: Path
    temp_path: Path | None
    backup_path: Path | None
    old_sha256: str | None
    new_sha256: str | None


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _invoke_fault(hook: FaultHook | None, event: str) -> None:
    if hook is not None:
        hook(event)


def _lock_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.lock")


def _temp_path(path: Path, transaction_id: str) -> Path:
    return path.with_name(f".{path.name}.tmp.{transaction_id}")


def _backup_path(path: Path, transaction_id: str) -> Path:
    return path.with_name(f"{path.name}.bak.{transaction_id}")


def _journal_path(path: Path, transaction_id: str) -> Path:
    return path.with_name(f".{path.name}.txn.{transaction_id}.json")


def _recovery_temp_path(path: Path, transaction_id: str) -> Path:
    return path.with_name(f".recovery.{transaction_id}.{uuid4().hex}")


def _pre_recovery_path(path: Path, transaction_id: str) -> Path:
    return path.with_name(f".pre-recovery.{transaction_id}")


def _journal_paths(path: Path) -> list[Path]:
    prefix = f".{path.name}.txn."
    suffix = ".json"
    if not path.parent.exists():
        return []
    return sorted(
        (
            item
            for item in path.parent.iterdir()
            if item.name.startswith(prefix) and item.name.endswith(suffix)
        ),
        key=lambda item: item.name,
    )


def _sync_directory(directory: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(str(directory), os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_new_synced(path: Path, data: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    descriptor = os.open(str(path), flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)


def _sync_file(path: Path) -> None:
    # Windows rejects fsync on a descriptor opened read-only (EBADF). The writer
    # already requires write access to replace this file, so reopen read/write.
    flags = os.O_RDWR
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    descriptor = os.open(str(path), flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _copy_synced(source: Path, destination: Path) -> None:
    data = source.read_bytes()
    _write_new_synced(destination, data)
    if _sha256(destination.read_bytes()) != _sha256(data):
        raise StorageError(f"Backup verification failed: {destination}")


def _windows_replace(path: Path, replacement: Path, backup: Path) -> None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    replace_file = kernel32.ReplaceFileW
    replace_file.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    replace_file.restype = ctypes.c_int
    ok = replace_file(
        str(path.absolute()),
        str(replacement.absolute()),
        str(backup.absolute()),
        0,
        None,
        None,
    )
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())


def _replace_with_backup(path: Path, replacement: Path, backup: Path | None) -> None:
    if not path.exists():
        os.replace(replacement, path)
        _sync_directory(path.parent)
        return
    if backup is None:
        raise StorageError("Existing targets require a backup path")
    if backup.exists():
        raise FileExistsError(f"Backup already exists: {backup}")
    if os.name == "nt":
        _windows_replace(path, replacement, backup)
        _sync_file(backup)
    else:
        backup_temp = backup.with_name(f".{backup.name}.tmp.{uuid4().hex}")
        try:
            _copy_synced(path, backup_temp)
            os.replace(backup_temp, backup)
            _sync_directory(path.parent)
            os.replace(replacement, path)
        finally:
            backup_temp.unlink(missing_ok=True)
    _sync_directory(path.parent)


class _TransactionLock:
    def __init__(self, path: Path) -> None:
        self.path = _lock_path(path)
        self.token = uuid4().hex
        self._owned = False

    def __enter__(self) -> _TransactionLock:
        payload = json.dumps(
            {
                "version": 1,
                "pid": os.getpid(),
                "created_unix": time.time(),
                "token": self.token,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        try:
            _write_new_synced(self.path, payload)
        except FileExistsError as exc:
            raise StorageBusyError(f"Storage lock already exists: {self.path}") from exc
        except Exception:
            # O_EXCL means a non-FileExists failure belongs to this attempt. Do
            # not leave a partial lock that would require manual quarantine.
            self.path.unlink(missing_ok=True)
            raise
        _sync_directory(self.path.parent)
        self._owned = True
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if not self._owned:
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return
        if raw.get("token") == self.token:
            self.path.unlink(missing_ok=True)
            _sync_directory(self.path.parent)


def require_clean_storage(path: Path) -> None:
    journals = _journal_paths(path)
    if journals:
        transaction_ids = tuple(_transaction_id_from_journal(path, item) for item in journals)
        raise RecoveryRequiredError(path, transaction_ids)


def atomic_write_bytes(
    path: Path,
    data: bytes,
    *,
    validator: Validator | None = None,
    expected_old_sha256: str | None = None,
    must_not_exist: bool = False,
    _fault: FaultHook | None = None,
) -> AtomicWriteReceipt:
    """Durably replace *path* without modifying its bytes in place.

    Backups are unique and are never pruned automatically. If a fault occurs after the
    durable journal is created, artifacts remain for explicit, inspect-first recovery.
    """

    if not isinstance(data, bytes):
        raise TypeError("atomic_write_bytes requires bytes")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise StorageError(f"Refusing to replace a symbolic link: {path}")

    transaction_id = uuid4().hex
    temp = _temp_path(path, transaction_id)
    journal = _journal_path(path, transaction_id)
    journal_created = False

    with _TransactionLock(path):
        require_clean_storage(path)
        if path.is_symlink():
            raise StorageError(f"Refusing to replace a symbolic link: {path}")
        had_live = path.exists()
        old_digest = _sha256(path.read_bytes()) if had_live else None
        if must_not_exist and had_live:
            raise FileExistsError(f"Target appeared before atomic create: {path}")
        if expected_old_sha256 is not None and old_digest != expected_old_sha256:
            raise ConcurrentStorageChangeError(
                f"Target changed while replacement was being prepared: {path}"
            )
        backup = _backup_path(path, transaction_id) if had_live else None
        new_digest = _sha256(data)
        try:
            _write_new_synced(temp, data)
            _invoke_fault(_fault, "after_temp_sync")
            readback = temp.read_bytes()
            if _sha256(readback) != new_digest:
                raise StorageError("Temporary file digest changed after fsync")
            if validator is not None:
                validator(readback)
            _invoke_fault(_fault, "after_validation")

            record = {
                "version": JOURNAL_VERSION,
                "transaction_id": transaction_id,
                "target": path.name,
                "temp": temp.name,
                "backup": backup.name if backup else None,
                "had_live": had_live,
                "old_sha256": old_digest,
                "new_sha256": new_digest,
                "created_unix": time.time(),
            }
            encoded_record = json.dumps(
                record,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            _write_new_synced(journal, encoded_record)
            _sync_directory(path.parent)
            journal_created = True
            _invoke_fault(_fault, "after_journal_sync")

            current_digest = _sha256(path.read_bytes()) if path.exists() else None
            if current_digest != old_digest:
                raise ConcurrentStorageChangeError(
                    f"Target changed immediately before atomic replacement: {path}"
                )

            _replace_with_backup(path, temp, backup)
            _invoke_fault(_fault, "after_replace")
            _sync_file(path)
            _invoke_fault(_fault, "after_live_sync")

            live = path.read_bytes()
            if _sha256(live) != new_digest:
                raise StorageError("Live file digest does not match committed data")
            if validator is not None:
                validator(live)
            _invoke_fault(_fault, "after_commit_validation")

            journal.unlink()
            _sync_directory(path.parent)
            return AtomicWriteReceipt(
                transaction_id=transaction_id,
                path=path,
                sha256=new_digest,
                backup_path=backup,
            )
        except Exception:
            if not journal_created:
                temp.unlink(missing_ok=True)
            raise


def _transaction_id_from_journal(path: Path, journal: Path) -> str:
    prefix = f".{path.name}.txn."
    suffix = ".json"
    if not (journal.name.startswith(prefix) and journal.name.endswith(suffix)):
        return "invalid"
    return journal.name[len(prefix) : -len(suffix)]


def _load_journal(path: Path, journal: Path) -> dict:
    if journal.is_symlink() or not journal.is_file():
        raise RecoveryAmbiguousError(f"Invalid recovery journal type: {journal}")
    if journal.stat().st_size > MAX_JOURNAL_BYTES:
        raise RecoveryAmbiguousError(f"Recovery journal is oversized: {journal}")
    try:
        record = json.loads(journal.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RecoveryAmbiguousError(f"Recovery journal is corrupt: {journal}") from exc
    transaction_id = _transaction_id_from_journal(path, journal)
    try:
        UUID(hex=transaction_id)
    except ValueError as exc:
        raise RecoveryAmbiguousError(f"Invalid transaction ID: {transaction_id}") from exc
    expected_temp = _temp_path(path, transaction_id).name
    expected_backup = _backup_path(path, transaction_id).name
    if (
        record.get("version") != JOURNAL_VERSION
        or record.get("transaction_id") != transaction_id
        or record.get("target") != path.name
        or record.get("temp") != expected_temp
        or record.get("backup") not in (None, expected_backup)
        or not isinstance(record.get("had_live"), bool)
        or not _DIGEST_RE.fullmatch(record.get("new_sha256", ""))
    ):
        raise RecoveryAmbiguousError(f"Recovery journal schema mismatch: {journal}")
    old_digest = record.get("old_sha256")
    if old_digest is not None and not _DIGEST_RE.fullmatch(old_digest):
        raise RecoveryAmbiguousError(f"Invalid old digest in journal: {journal}")
    if record["had_live"] != (old_digest is not None and record["backup"] is not None):
        raise RecoveryAmbiguousError(f"Inconsistent prior-file state: {journal}")
    return record


def _candidate_matches(
    candidate: Path | None,
    expected_digest: str | None,
    validator: Validator | None,
) -> bool:
    if candidate is None or expected_digest is None:
        return False
    if not candidate.exists() or candidate.is_symlink() or not candidate.is_file():
        return False
    try:
        data = candidate.read_bytes()
        if _sha256(data) != expected_digest:
            return False
        if validator is not None:
            validator(data)
        return True
    except Exception:
        return False


def _candidate_is_valid(candidate: Path, validator: Validator | None) -> bool:
    if validator is None:
        return False
    if not candidate.exists() or candidate.is_symlink() or not candidate.is_file():
        return False
    try:
        data = candidate.read_bytes()
        if validator is not None:
            validator(data)
        return True
    except Exception:
        return False


def inspect_recovery(path: Path, *, validator: Validator | None = None) -> list[RecoveryPlan]:
    """Read recovery metadata without changing files."""

    path = Path(path)
    plans: list[RecoveryPlan] = []
    for journal in _journal_paths(path):
        transaction_id = _transaction_id_from_journal(path, journal)
        try:
            record = _load_journal(path, journal)
            temp = path.parent / record["temp"]
            backup = path.parent / record["backup"] if record["backup"] else None
            old_digest = record["old_sha256"]
            new_digest = record["new_sha256"]
            live_is_new = _candidate_matches(path, new_digest, validator)
            live_is_old = _candidate_matches(path, old_digest, validator)
            if path.exists() and not live_is_new and not live_is_old and _candidate_is_valid(
                path, validator
            ):
                action = "manual"
            elif live_is_new:
                action = "finalize_committed"
            elif live_is_old:
                action = "discard_uncommitted"
            elif _candidate_matches(temp, new_digest, validator):
                action = "restore_new"
            elif _candidate_matches(backup, old_digest, validator):
                action = "restore_backup"
            else:
                action = "manual"
        except RecoveryAmbiguousError:
            temp = None
            backup = None
            old_digest = None
            new_digest = None
            action = "manual"
        plans.append(
            RecoveryPlan(
                transaction_id=transaction_id,
                action=action,
                path=path,
                journal_path=journal,
                temp_path=temp,
                backup_path=backup,
                old_sha256=old_digest,
                new_sha256=new_digest,
            )
        )
    return plans


def _select_plan(
    path: Path,
    transaction_id: str | None,
    validator: Validator | None,
) -> RecoveryPlan:
    plans = inspect_recovery(path, validator=validator)
    if transaction_id is not None:
        plans = [plan for plan in plans if plan.transaction_id == transaction_id]
    if len(plans) != 1:
        raise RecoveryAmbiguousError(
            f"Expected one recovery transaction for {path}; found {len(plans)}"
        )
    return plans[0]


def recover_atomic_file(
    path: Path,
    *,
    validator: Validator | None = None,
    transaction_id: str | None = None,
    dry_run: bool = True,
) -> RecoveryPlan:
    """Inspect or explicitly apply one deterministic interrupted transaction."""

    path = Path(path)
    plan = _select_plan(path, transaction_id, validator)
    if dry_run:
        return plan
    if plan.action == "manual":
        raise RecoveryAmbiguousError(f"Manual recovery required for {plan.journal_path}")

    with _TransactionLock(path):
        plan = _select_plan(path, plan.transaction_id, validator)
        if plan.action == "manual":
            raise RecoveryAmbiguousError(f"Manual recovery required for {plan.journal_path}")

        if plan.action in ("restore_new", "restore_backup"):
            source = plan.temp_path if plan.action == "restore_new" else plan.backup_path
            if source is None:
                raise RecoveryAmbiguousError("Recovery source is missing")
            recovery_temp = _recovery_temp_path(path, plan.transaction_id)
            try:
                _copy_synced(source, recovery_temp)
                candidate = recovery_temp.read_bytes()
                if validator is not None:
                    validator(candidate)
                prior = _pre_recovery_path(path, plan.transaction_id) if path.exists() else None
                _replace_with_backup(path, recovery_temp, prior)
                _sync_file(path)
            finally:
                recovery_temp.unlink(missing_ok=True)

        if plan.action in ("finalize_committed", "restore_new", "restore_backup"):
            expected = plan.new_sha256 if plan.action != "restore_backup" else plan.old_sha256
            if not _candidate_matches(path, expected, validator):
                raise RecoveryAmbiguousError("Recovered live file failed validation")

        if plan.temp_path is not None:
            plan.temp_path.unlink(missing_ok=True)
        plan.journal_path.unlink()
        _sync_directory(path.parent)
    return plan


def quarantine_stale_lock(
    path: Path,
    *,
    min_age_seconds: int = DEFAULT_STALE_LOCK_SECONDS,
    dry_run: bool = True,
) -> Path:
    """Explicitly quarantine (never delete) a sufficiently old transaction lock."""

    if min_age_seconds < 60:
        raise ValueError("min_age_seconds must be at least 60")
    lock = _lock_path(Path(path))
    before = lock.stat()
    age = time.time() - before.st_mtime
    if age < min_age_seconds:
        raise StorageBusyError(
            f"Lock is {age:.1f}s old; minimum quarantine age is {min_age_seconds}s"
        )
    original = lock.read_bytes()
    if dry_run:
        return lock
    after = lock.stat()
    if (
        before.st_mtime_ns != after.st_mtime_ns
        or before.st_size != after.st_size
        or lock.read_bytes() != original
    ):
        raise StorageBusyError("Lock changed during stale-lock inspection")
    quarantine = lock.with_name(f"{lock.name}.stale.{uuid4().hex}")
    os.replace(lock, quarantine)
    _sync_directory(lock.parent)
    return quarantine


def list_backups(path: Path) -> list[Path]:
    """Return backups newest first; this function never removes them."""

    path = Path(path)
    prefix = f"{path.name}.bak."
    if not path.parent.exists():
        return []
    backups = [
        item
        for item in path.parent.iterdir()
        if item.name.startswith(prefix) and item.is_file() and not item.is_symlink()
    ]
    return sorted(backups, key=lambda item: item.stat().st_mtime_ns, reverse=True)

from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable
from uuid import UUID, uuid4

from vault_unified.crypto import decrypt_payload
from vault_unified.models import SecretEntry, Source, SyncStatus
from vault_unified.storage import (
    AtomicWriteReceipt,
    RecoveryPlan,
    atomic_write_bytes,
    inspect_recovery,
    list_backups,
    recover_atomic_file,
    require_clean_storage,
)
from vault_unified.v3_crypto import (
    V3PayloadError,
    create_v3_container,
    decrypt_v3_payload,
    validate_v3_payload,
)
from vault_unified.vault_format import LegacyContainer, V3Container, parse_vault_container


RECEIPT_VERSION = 1
MIN_FREE_SPACE_BYTES = 1024 * 1024
MAX_RECEIPT_BYTES = 64 * 1024
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_TX_RE = re.compile(r"^[0-9a-f]{32}$")
_STATES = frozenset(
    {"planned", "backup_created", "candidate_validated", "activated", "rolled_back"}
)
MigrationFault = Callable[[str], None]


class MigrationError(ValueError):
    """A migration artifact, state transition, or equivalence check is unsafe."""


class MigrationSpaceError(MigrationError):
    """The destination filesystem lacks the conservative free-space reserve."""


@dataclass(frozen=True)
class MigrationReceipt:
    version: int
    migration_id: str
    state: str
    target_name: str
    backup_name: str
    candidate_name: str
    source_format: str
    target_format: int
    legacy_sha256: str
    candidate_sha256: str | None
    vault_id: str | None
    entry_count: int
    created_unix: int
    activation_transaction_id: str | None
    activation_backup_name: str | None
    rollback_transaction_id: str | None
    rollback_backup_name: str | None


@dataclass(frozen=True)
class MigrationOutcome:
    action: str
    state: str
    changed: bool
    target_path: Path
    receipt_path: Path | None
    backup_path: Path | None
    candidate_path: Path | None
    legacy_sha256: str
    candidate_sha256: str | None
    vault_id: str | None
    entry_count: int
    required_free_bytes: int
    available_free_bytes: int


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _fault(hook: MigrationFault | None, event: str) -> None:
    if hook is not None:
        hook(event)


def _normalize_legacy_payload(payload: Any) -> dict:
    if not isinstance(payload, dict) or set(payload) != {"version", "entries"}:
        raise MigrationError("Legacy payload must contain only version and entries")
    version = payload["version"]
    if isinstance(version, bool) or not isinstance(version, int) or version not in (1, 2):
        raise MigrationError("Only legacy payload versions 1 and 2 can migrate")
    entries = payload["entries"]
    if not isinstance(entries, dict) or len(entries) > 100_000:
        raise MigrationError("Legacy entries must be an object")
    normalized_entries: dict[str, dict] = {}
    for item_id, raw in entries.items():
        if not isinstance(item_id, str) or not isinstance(raw, dict):
            raise MigrationError("Legacy entry IDs must map to objects")
        item = copy.deepcopy(raw)
        if version == 1:
            item.setdefault("sync_status", SyncStatus.CLEAN.value)
            item.setdefault("last_synced_at", "")
            item.setdefault("remote_updated_at", "")
            item.setdefault("proton_share_id", "")
            item.setdefault("linked_sources", {})
            if not isinstance(item["linked_sources"], dict):
                raise MigrationError(f"Legacy linked_sources is invalid: {item_id}")
            if item.get("external_id") and item.get("source") not in (
                None,
                Source.LOCAL.value,
            ):
                source = item["source"]
                item["linked_sources"].setdefault(source, item["external_id"])
        try:
            SecretEntry.from_dict(item)
        except (TypeError, ValueError) as exc:
            raise MigrationError(f"Legacy entry is not loadable: {item_id}") from exc
        normalized_entries[item_id] = item
    normalized = {"version": 2, "entries": normalized_entries}
    try:
        validate_v3_payload(normalized)
    except V3PayloadError as exc:
        raise MigrationError("Legacy payload exceeds Vault Format v3 bounds") from exc
    return normalized


def _read_legacy(path: Path, password: str) -> tuple[bytes, dict]:
    require_clean_storage(path)
    if not path.exists() or path.is_symlink() or not path.is_file():
        raise MigrationError(f"Legacy source must be a regular existing file: {path}")
    source = path.read_bytes()
    if not isinstance(parse_vault_container(source), LegacyContainer):
        raise MigrationError("Migration source is not a legacy v1/v2 container")
    try:
        payload = decrypt_payload(password, source)
    except Exception as exc:
        raise MigrationError("Legacy authentication or payload decoding failed") from exc
    return source, _normalize_legacy_payload(payload)


def _validate_legacy(
    value: bytes,
    password: str,
    expected_sha256: str,
    expected_payload: dict | None = None,
) -> dict:
    if _sha256(value) != expected_sha256:
        raise MigrationError("Legacy artifact digest does not match its receipt")
    if not isinstance(parse_vault_container(value), LegacyContainer):
        raise MigrationError("Legacy artifact changed format")
    try:
        normalized = _normalize_legacy_payload(decrypt_payload(password, value))
    except Exception as exc:
        raise MigrationError("Legacy artifact no longer authenticates") from exc
    if expected_payload is not None and normalized != expected_payload:
        raise MigrationError("Legacy artifact payload is not equivalent")
    return normalized


def _validate_candidate(
    value: bytes,
    password: str,
    expected_payload: dict,
    expected_sha256: str | None = None,
) -> V3Container:
    if expected_sha256 is not None and _sha256(value) != expected_sha256:
        raise MigrationError("V3 candidate digest does not match its receipt")
    parsed = parse_vault_container(value)
    if not isinstance(parsed, V3Container):
        raise MigrationError("Migration candidate is not Vault Format v3")
    try:
        decrypted = decrypt_v3_payload(password, parsed)
    except Exception as exc:
        raise MigrationError("V3 candidate authentication failed") from exc
    if decrypted != expected_payload:
        raise MigrationError("V3 candidate is not payload-equivalent to the legacy backup")
    if parsed.header.generation != 1 or parsed.header.key_generation != 1:
        raise MigrationError("A migration candidate must start at generation 1")
    return parsed


def _required_free_bytes(source: bytes, normalized: dict) -> int:
    plaintext_bytes = len(_canonical_json(normalized))
    return max(
        MIN_FREE_SPACE_BYTES,
        3 * len(source) + 3 * plaintext_bytes + 3 * MAX_RECEIPT_BYTES,
    )


def _free_bytes(path: Path) -> int:
    return shutil.disk_usage(path.parent).free


def _artifact_names(target_name: str, migration_id: str) -> tuple[str, str, str]:
    stem = f"{target_name}.migration-v3.{migration_id}"
    return f"{stem}.legacy", f"{stem}.candidate", f"{stem}.json"


def _receipt_dict(receipt: MigrationReceipt) -> dict[str, Any]:
    return {
        "version": receipt.version,
        "migration_id": receipt.migration_id,
        "state": receipt.state,
        "target_name": receipt.target_name,
        "backup_name": receipt.backup_name,
        "candidate_name": receipt.candidate_name,
        "source_format": receipt.source_format,
        "target_format": receipt.target_format,
        "legacy_sha256": receipt.legacy_sha256,
        "candidate_sha256": receipt.candidate_sha256,
        "vault_id": receipt.vault_id,
        "entry_count": receipt.entry_count,
        "created_unix": receipt.created_unix,
        "activation_transaction_id": receipt.activation_transaction_id,
        "activation_backup_name": receipt.activation_backup_name,
        "rollback_transaction_id": receipt.rollback_transaction_id,
        "rollback_backup_name": receipt.rollback_backup_name,
    }


def _reject_duplicate_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise MigrationError(f"Duplicate migration receipt field: {key}")
        result[key] = value
    return result


def _nullable_string(value: Any, name: str) -> str | None:
    if value is not None and not isinstance(value, str):
        raise MigrationError(f"Receipt {name} must be a string or null")
    return value


def _parse_receipt(value: bytes, receipt_path: Path) -> MigrationReceipt:
    if len(value) > MAX_RECEIPT_BYTES:
        raise MigrationError("Migration receipt is oversized")
    try:
        raw = json.loads(
            value.decode("utf-8", errors="strict"),
            object_pairs_hook=_reject_duplicate_fields,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MigrationError("Migration receipt is not strict UTF-8 JSON") from exc
    required = {
        "version",
        "migration_id",
        "state",
        "target_name",
        "backup_name",
        "candidate_name",
        "source_format",
        "target_format",
        "legacy_sha256",
        "candidate_sha256",
        "vault_id",
        "entry_count",
        "created_unix",
        "activation_transaction_id",
        "activation_backup_name",
        "rollback_transaction_id",
        "rollback_backup_name",
    }
    if not isinstance(raw, dict) or set(raw) != required:
        raise MigrationError("Migration receipt schema is closed and exact")
    if (
        isinstance(raw["version"], bool)
        or not isinstance(raw["version"], int)
        or raw["version"] != RECEIPT_VERSION
    ):
        raise MigrationError("Unsupported migration receipt version")
    try:
        migration_id = UUID(raw["migration_id"])
    except (ValueError, TypeError, AttributeError) as exc:
        raise MigrationError("Receipt migration_id is invalid") from exc
    if str(migration_id) != raw["migration_id"]:
        raise MigrationError("Receipt migration_id is not canonical")
    if raw["state"] not in _STATES:
        raise MigrationError("Receipt state is invalid")
    target_name = raw["target_name"]
    try:
        target_name.encode("utf-8")
    except (AttributeError, UnicodeEncodeError) as exc:
        raise MigrationError("Receipt target_name must be valid Unicode") from exc
    if (
        not target_name
        or target_name in (".", "..")
        or Path(target_name).name != target_name
    ):
        raise MigrationError("Receipt target_name must be a basename")
    backup_name, candidate_name, receipt_name = _artifact_names(
        target_name, raw["migration_id"]
    )
    if (
        raw["backup_name"] != backup_name
        or raw["candidate_name"] != candidate_name
        or receipt_path.name != receipt_name
    ):
        raise MigrationError("Receipt artifact names are not canonical")
    if (
        raw["source_format"] != "legacy-v1-v2"
        or isinstance(raw["target_format"], bool)
        or not isinstance(raw["target_format"], int)
        or raw["target_format"] != 3
    ):
        raise MigrationError("Receipt format transition is invalid")
    if not isinstance(raw["legacy_sha256"], str) or not _DIGEST_RE.fullmatch(
        raw["legacy_sha256"]
    ):
        raise MigrationError("Receipt legacy digest is invalid")
    candidate_sha256 = _nullable_string(raw["candidate_sha256"], "candidate_sha256")
    if candidate_sha256 is not None and not _DIGEST_RE.fullmatch(candidate_sha256):
        raise MigrationError("Receipt candidate digest is invalid")
    vault_id = _nullable_string(raw["vault_id"], "vault_id")
    if vault_id is not None:
        try:
            if str(UUID(vault_id)) != vault_id:
                raise ValueError
        except (ValueError, AttributeError) as exc:
            raise MigrationError("Receipt vault_id is invalid") from exc
    for name in ("entry_count", "created_unix"):
        if isinstance(raw[name], bool) or not isinstance(raw[name], int) or raw[name] < 0:
            raise MigrationError(f"Receipt {name} is invalid")
    if raw["entry_count"] > 100_000:
        raise MigrationError("Receipt entry_count exceeds the V3 limit")
    activation_tx = _nullable_string(
        raw["activation_transaction_id"], "activation_transaction_id"
    )
    rollback_tx = _nullable_string(raw["rollback_transaction_id"], "rollback_transaction_id")
    for name, tx in (("activation", activation_tx), ("rollback", rollback_tx)):
        if tx is not None and not _TX_RE.fullmatch(tx):
            raise MigrationError(f"Receipt {name} transaction ID is invalid")
    activation_backup = _nullable_string(
        raw["activation_backup_name"], "activation_backup_name"
    )
    rollback_backup = _nullable_string(raw["rollback_backup_name"], "rollback_backup_name")
    for name, tx, backup in (
        ("activation", activation_tx, activation_backup),
        ("rollback", rollback_tx, rollback_backup),
    ):
        if backup is not None and (
            tx is None or backup != f"{target_name}.bak.{tx}" or Path(backup).name != backup
        ):
            raise MigrationError(f"Receipt {name} backup name is invalid")
    has_candidate = candidate_sha256 is not None and vault_id is not None
    if raw["state"] in ("planned", "backup_created") and (
        candidate_sha256 is not None or vault_id is not None
    ):
        raise MigrationError("Pre-candidate receipt contains candidate identity")
    if raw["state"] in ("candidate_validated", "activated", "rolled_back") and not has_candidate:
        raise MigrationError("Post-candidate receipt lacks candidate identity")
    if raw["state"] != "rolled_back" and (
        rollback_tx is not None or rollback_backup is not None
    ):
        raise MigrationError("Non-rollback receipt contains rollback evidence")
    return MigrationReceipt(
        version=RECEIPT_VERSION,
        migration_id=raw["migration_id"],
        state=raw["state"],
        target_name=target_name,
        backup_name=backup_name,
        candidate_name=candidate_name,
        source_format="legacy-v1-v2",
        target_format=3,
        legacy_sha256=raw["legacy_sha256"],
        candidate_sha256=candidate_sha256,
        vault_id=vault_id,
        entry_count=raw["entry_count"],
        created_unix=raw["created_unix"],
        activation_transaction_id=activation_tx,
        activation_backup_name=activation_backup,
        rollback_transaction_id=rollback_tx,
        rollback_backup_name=rollback_backup,
    )


def load_migration_receipt(path: Path) -> MigrationReceipt:
    path = Path(path)
    require_clean_storage(path)
    if not path.exists() or path.is_symlink() or not path.is_file():
        raise MigrationError(f"Migration receipt must be a regular file: {path}")
    return _parse_receipt(path.read_bytes(), path)


def inspect_migration_receipt_recovery(path: Path) -> list[RecoveryPlan]:
    path = Path(path)
    return inspect_recovery(path, validator=lambda value: _parse_receipt(value, path))


def recover_migration_receipt(
    path: Path,
    *,
    transaction_id: str | None = None,
    apply: bool = False,
) -> RecoveryPlan:
    path = Path(path)
    return recover_atomic_file(
        path,
        validator=lambda value: _parse_receipt(value, path),
        transaction_id=transaction_id,
        dry_run=not apply,
    )


def _write_receipt(path: Path, receipt: MigrationReceipt) -> None:
    encoded = _canonical_json(_receipt_dict(receipt))

    def validate(candidate: bytes) -> None:
        if _parse_receipt(candidate, path) != receipt:
            raise MigrationError("Migration receipt did not round-trip")

    if path.exists():
        prior = path.read_bytes()
        atomic_write_bytes(
            path,
            encoded,
            validator=validate,
            expected_old_sha256=_sha256(prior),
        )
    else:
        atomic_write_bytes(path, encoded, validator=validate, must_not_exist=True)


def _paths(receipt_path: Path, receipt: MigrationReceipt) -> tuple[Path, Path, Path]:
    parent = receipt_path.parent
    return (
        parent / receipt.target_name,
        parent / receipt.backup_name,
        parent / receipt.candidate_name,
    )


def _matching_backup(path: Path, expected_sha256: str) -> Path | None:
    for backup in list_backups(path):
        try:
            if _sha256(backup.read_bytes()) == expected_sha256:
                return backup
        except OSError:
            continue
    return None


def _read_artifact(path: Path, label: str) -> bytes:
    require_clean_storage(path)
    if not path.exists() or path.is_symlink() or not path.is_file():
        raise MigrationError(f"{label} must be a regular existing file: {path}")
    return path.read_bytes()


def _outcome(
    action: str,
    changed: bool,
    target: Path,
    receipt_path: Path | None,
    backup: Path | None,
    candidate: Path | None,
    legacy_sha256: str,
    candidate_sha256: str | None,
    vault_id: str | None,
    entry_count: int,
    required: int,
    available: int,
    state: str,
) -> MigrationOutcome:
    return MigrationOutcome(
        action=action,
        state=state,
        changed=changed,
        target_path=target,
        receipt_path=receipt_path,
        backup_path=backup,
        candidate_path=candidate,
        legacy_sha256=legacy_sha256,
        candidate_sha256=candidate_sha256,
        vault_id=vault_id,
        entry_count=entry_count,
        required_free_bytes=required,
        available_free_bytes=available,
    )


def plan_v3_migration(path: Path, legacy_password: str) -> MigrationOutcome:
    path = Path(path)
    source, normalized = _read_legacy(path, legacy_password)
    required = _required_free_bytes(source, normalized)
    available = _free_bytes(path)
    return _outcome(
        "dry-run",
        False,
        path,
        None,
        None,
        None,
        _sha256(source),
        None,
        None,
        len(normalized["entries"]),
        required,
        available,
        "planned",
    )


def _active_receipts(path: Path) -> list[Path]:
    active: list[Path] = []
    for receipt_path in discover_migration_receipts(path):
        if not receipt_path.exists():
            active.append(receipt_path)
            continue
        receipt = load_migration_receipt(receipt_path)
        if receipt.state != "rolled_back":
            active.append(receipt_path)
    return sorted(active, key=lambda item: item.name)


def discover_migration_receipts(path: Path) -> list[Path]:
    """List canonical live or journal-referenced receipts without modifying evidence."""

    path = Path(path)
    if not path.parent.exists():
        return []
    uuid_pattern = (
        r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
        r"[89ab][0-9a-f]{3}-[0-9a-f]{12}"
    )
    receipt_pattern = rf"{re.escape(path.name)}\.migration-v3\.{uuid_pattern}\.json"
    live = re.compile(rf"^{receipt_pattern}$")
    journal = re.compile(rf"^\.(?P<receipt>{receipt_pattern})\.txn\.[0-9a-f]{{32}}\.json$")
    discovered: set[Path] = set()
    for item in path.parent.iterdir():
        if live.fullmatch(item.name):
            discovered.add(item)
            continue
        match = journal.fullmatch(item.name)
        if match:
            discovered.add(path.parent / match.group("receipt"))
    return sorted(discovered, key=lambda item: item.name)


def _advance_migration(
    receipt_path: Path,
    legacy_password: str,
    v3_password: str,
    *,
    dry_run: bool,
    _fault_hook: MigrationFault | None = None,
) -> MigrationOutcome:
    receipt = load_migration_receipt(receipt_path)
    if receipt.state == "rolled_back":
        raise MigrationError("A rolled-back receipt cannot be resumed")
    target, backup, candidate = _paths(receipt_path, receipt)
    require_clean_storage(target)
    require_clean_storage(backup)
    require_clean_storage(candidate)
    required = MIN_FREE_SPACE_BYTES
    available = _free_bytes(target)

    if backup.exists():
        legacy_bytes = _read_artifact(backup, "Immutable legacy backup")
        normalized = _validate_legacy(
            legacy_bytes,
            legacy_password,
            receipt.legacy_sha256,
        )
    else:
        if receipt.state != "planned":
            raise MigrationError(
                "Receipt says the immutable legacy backup exists, but it is missing"
            )
        live_bytes, normalized = _read_legacy(target, legacy_password)
        if _sha256(live_bytes) != receipt.legacy_sha256:
            raise MigrationError("Live legacy source changed before backup creation")
        legacy_bytes = live_bytes
    if len(normalized["entries"]) != receipt.entry_count:
        raise MigrationError("Receipt entry count does not match the legacy payload")
    required = _required_free_bytes(legacy_bytes, normalized)

    if dry_run:
        if receipt.candidate_sha256 is not None:
            candidate_bytes = _read_artifact(candidate, "V3 migration candidate")
            parsed = _validate_candidate(
                candidate_bytes,
                v3_password,
                normalized,
                receipt.candidate_sha256,
            )
            if parsed.header.vault_id != receipt.vault_id:
                raise MigrationError("Receipt vault_id does not match the V3 candidate")
        elif candidate.exists():
            _validate_candidate(
                _read_artifact(candidate, "V3 migration candidate"),
                v3_password,
                normalized,
            )
        live_digest = _sha256(target.read_bytes()) if target.exists() else ""
        if receipt.candidate_sha256 and live_digest == receipt.candidate_sha256:
            action = "finalize-activation" if receipt.state != "activated" else "complete"
        elif live_digest == receipt.legacy_sha256:
            action = "activate" if receipt.candidate_sha256 else "resume-build"
        else:
            raise MigrationError("Live file is neither the recorded legacy nor V3 candidate")
        return _outcome(
            action,
            False,
            target,
            receipt_path,
            backup,
            candidate,
            receipt.legacy_sha256,
            receipt.candidate_sha256,
            receipt.vault_id,
            receipt.entry_count,
            required,
            available,
            receipt.state,
        )

    live_before = target.read_bytes() if target.exists() else b""
    already_complete = (
        receipt.state == "activated"
        and receipt.candidate_sha256 is not None
        and _sha256(live_before) == receipt.candidate_sha256
    )
    if not already_complete and available < required:
        raise MigrationSpaceError(
            f"Migration requires {required} free bytes; only {available} are available"
        )

    changed = False
    if not backup.exists():
        atomic_write_bytes(
            backup,
            legacy_bytes,
            validator=lambda value: _validate_legacy(
                value, legacy_password, receipt.legacy_sha256, normalized
            ),
            must_not_exist=True,
        )
        changed = True
        _fault(_fault_hook, "after_backup_create")
    if receipt.state == "planned":
        receipt = replace(receipt, state="backup_created")
        _write_receipt(receipt_path, receipt)
        changed = True
        _fault(_fault_hook, "after_backup_receipt")

    if candidate.exists():
        candidate_bytes = _read_artifact(candidate, "V3 migration candidate")
        parsed = _validate_candidate(
            candidate_bytes,
            v3_password,
            normalized,
            receipt.candidate_sha256,
        )
        candidate_sha256 = _sha256(candidate_bytes)
    else:
        if receipt.candidate_sha256 is not None:
            raise MigrationError("Receipt candidate is missing and cannot be regenerated")
        candidate_bytes = create_v3_container(v3_password, normalized)
        parsed = _validate_candidate(candidate_bytes, v3_password, normalized)
        candidate_sha256 = _sha256(candidate_bytes)
        atomic_write_bytes(
            candidate,
            candidate_bytes,
            validator=lambda value: _validate_candidate(
                value, v3_password, normalized, candidate_sha256
            ),
            must_not_exist=True,
        )
        changed = True
        _fault(_fault_hook, "after_candidate_create")
    if receipt.candidate_sha256 is None:
        receipt = replace(
            receipt,
            state="candidate_validated",
            candidate_sha256=candidate_sha256,
            vault_id=parsed.header.vault_id,
        )
        _write_receipt(receipt_path, receipt)
        changed = True
        _fault(_fault_hook, "after_candidate_receipt")
    elif receipt.vault_id != parsed.header.vault_id:
        raise MigrationError("Receipt vault_id does not match the V3 candidate")

    live = target.read_bytes()
    live_digest = _sha256(live)
    activation: AtomicWriteReceipt | None = None
    if live_digest == receipt.legacy_sha256:
        _validate_legacy(live, legacy_password, receipt.legacy_sha256, normalized)
        activation = atomic_write_bytes(
            target,
            candidate_bytes,
            validator=lambda value: _validate_candidate(
                value, v3_password, normalized, candidate_sha256
            ),
            expected_old_sha256=receipt.legacy_sha256,
        )
        changed = True
        _fault(_fault_hook, "after_activation")
    elif live_digest == candidate_sha256:
        _validate_candidate(live, v3_password, normalized, candidate_sha256)
    else:
        raise MigrationError("Live file changed to an unrecorded version before activation")

    if receipt.state != "activated":
        if activation is not None:
            activation_tx = activation.transaction_id
            activation_backup = (
                activation.backup_path.name if activation.backup_path is not None else None
            )
        else:
            matched = _matching_backup(target, receipt.legacy_sha256)
            activation_backup = matched.name if matched else None
            activation_tx = (
                activation_backup.rsplit(".", 1)[-1] if activation_backup else None
            )
        receipt = replace(
            receipt,
            state="activated",
            activation_transaction_id=activation_tx,
            activation_backup_name=activation_backup,
        )
        _write_receipt(receipt_path, receipt)
        changed = True
        _fault(_fault_hook, "after_activation_receipt")
    return _outcome(
        "activated",
        changed,
        target,
        receipt_path,
        backup,
        candidate,
        receipt.legacy_sha256,
        receipt.candidate_sha256,
        receipt.vault_id,
        receipt.entry_count,
        required,
        available,
        receipt.state,
    )


def apply_v3_migration(
    path: Path,
    legacy_password: str,
    v3_password: str,
    *,
    _fault_hook: MigrationFault | None = None,
) -> MigrationOutcome:
    path = Path(path)
    source, normalized = _read_legacy(path, legacy_password)
    required = _required_free_bytes(source, normalized)
    available = _free_bytes(path)
    if available < required:
        raise MigrationSpaceError(
            f"Migration requires {required} free bytes; only {available} are available"
        )
    active = _active_receipts(path)
    if active:
        raise MigrationError(f"An unfinished migration receipt already exists: {active[0]}")
    migration_id = str(uuid4())
    backup_name, candidate_name, receipt_name = _artifact_names(path.name, migration_id)
    receipt_path = path.parent / receipt_name
    receipt = MigrationReceipt(
        version=RECEIPT_VERSION,
        migration_id=migration_id,
        state="planned",
        target_name=path.name,
        backup_name=backup_name,
        candidate_name=candidate_name,
        source_format="legacy-v1-v2",
        target_format=3,
        legacy_sha256=_sha256(source),
        candidate_sha256=None,
        vault_id=None,
        entry_count=len(normalized["entries"]),
        created_unix=int(time.time()),
        activation_transaction_id=None,
        activation_backup_name=None,
        rollback_transaction_id=None,
        rollback_backup_name=None,
    )
    _write_receipt(receipt_path, receipt)
    _fault(_fault_hook, "after_receipt_planned")
    return _advance_migration(
        receipt_path,
        legacy_password,
        v3_password,
        dry_run=False,
        _fault_hook=_fault_hook,
    )


def inspect_v3_migration(
    receipt_path: Path,
    legacy_password: str,
    v3_password: str,
) -> MigrationOutcome:
    return _advance_migration(
        Path(receipt_path),
        legacy_password,
        v3_password,
        dry_run=True,
    )


def resume_v3_migration(
    receipt_path: Path,
    legacy_password: str,
    v3_password: str,
    *,
    apply: bool = False,
) -> MigrationOutcome:
    return _advance_migration(
        Path(receipt_path),
        legacy_password,
        v3_password,
        dry_run=not apply,
    )


def rollback_v3_migration(
    receipt_path: Path,
    legacy_password: str,
    v3_password: str,
    *,
    apply: bool = False,
    _fault_hook: MigrationFault | None = None,
) -> MigrationOutcome:
    receipt_path = Path(receipt_path)
    receipt = load_migration_receipt(receipt_path)
    if receipt.state not in ("activated", "rolled_back"):
        raise MigrationError("Only an activated migration can roll back")
    if receipt.candidate_sha256 is None or receipt.vault_id is None:
        raise MigrationError("Activated receipt lacks V3 candidate identity")
    target, backup, candidate = _paths(receipt_path, receipt)
    require_clean_storage(target)
    require_clean_storage(backup)
    require_clean_storage(candidate)
    if not backup.exists() or not candidate.exists() or not target.exists():
        raise MigrationError("Rollback requires live, immutable legacy backup, and V3 candidate")
    legacy_bytes = _read_artifact(backup, "Immutable legacy backup")
    normalized = _validate_legacy(
        legacy_bytes,
        legacy_password,
        receipt.legacy_sha256,
    )
    candidate_bytes = _read_artifact(candidate, "V3 migration candidate")
    parsed = _validate_candidate(
        candidate_bytes,
        v3_password,
        normalized,
        receipt.candidate_sha256,
    )
    if parsed.header.vault_id != receipt.vault_id:
        raise MigrationError("Rollback candidate vault_id does not match the receipt")
    live = target.read_bytes()
    live_digest = _sha256(live)
    required = _required_free_bytes(legacy_bytes, normalized)
    available = _free_bytes(target)
    if live_digest == receipt.candidate_sha256:
        _validate_candidate(live, v3_password, normalized, receipt.candidate_sha256)
        action = "restore-legacy"
    elif live_digest == receipt.legacy_sha256:
        _validate_legacy(live, legacy_password, receipt.legacy_sha256, normalized)
        action = "finalize-rollback" if receipt.state != "rolled_back" else "complete"
    else:
        raise MigrationError("Live file is neither the activated V3 nor immutable legacy version")
    if not apply:
        return _outcome(
            action,
            False,
            target,
            receipt_path,
            backup,
            candidate,
            receipt.legacy_sha256,
            receipt.candidate_sha256,
            receipt.vault_id,
            receipt.entry_count,
            required,
            available,
            receipt.state,
        )
    if available < required:
        raise MigrationSpaceError(
            f"Rollback requires {required} free bytes; only {available} are available"
        )
    changed = False
    rollback: AtomicWriteReceipt | None = None
    if live_digest == receipt.candidate_sha256:
        rollback = atomic_write_bytes(
            target,
            legacy_bytes,
            validator=lambda value: _validate_legacy(
                value, legacy_password, receipt.legacy_sha256, normalized
            ),
            expected_old_sha256=receipt.candidate_sha256,
        )
        changed = True
        _fault(_fault_hook, "after_rollback")
    if receipt.state != "rolled_back":
        if rollback is not None:
            rollback_tx = rollback.transaction_id
            rollback_backup = (
                rollback.backup_path.name if rollback.backup_path is not None else None
            )
        else:
            matched = _matching_backup(target, receipt.candidate_sha256)
            rollback_backup = matched.name if matched else None
            rollback_tx = rollback_backup.rsplit(".", 1)[-1] if rollback_backup else None
        receipt = replace(
            receipt,
            state="rolled_back",
            rollback_transaction_id=rollback_tx,
            rollback_backup_name=rollback_backup,
        )
        _write_receipt(receipt_path, receipt)
        changed = True
        _fault(_fault_hook, "after_rollback_receipt")
    return _outcome(
        "rolled-back",
        changed,
        target,
        receipt_path,
        backup,
        candidate,
        receipt.legacy_sha256,
        receipt.candidate_sha256,
        receipt.vault_id,
        receipt.entry_count,
        required,
        available,
        receipt.state,
    )

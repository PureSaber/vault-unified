from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

LEDGER_VERSION = 1
TOMBSTONE_RETENTION_DAYS = 30
CONTENT_FIELDS = ("title", "username", "password", "url", "notes", "tags")
REMOTE_SYNC_FIELDS = ("title", "username", "password", "url", "notes")
OPERATION_KINDS = frozenset({"create", "update", "delete"})
OPERATION_STATES = frozenset({"intent", "unknown", "acknowledged"})


class SyncLedgerError(ValueError):
    """Encrypted sync metadata is malformed or violates the state machine."""


@dataclass(frozen=True)
class AdapterCapabilities:
    authoritative_list: bool = False
    revision_token: bool = False
    idempotent_create: bool = False
    delete_confirm: bool = False
    absence_is_delete: bool = False

    def to_dict(self) -> dict[str, bool]:
        return {
            "authoritative_list": self.authoritative_list,
            "revision_token": self.revision_token,
            "idempotent_create": self.idempotent_create,
            "delete_confirm": self.delete_confirm,
            "absence_is_delete": self.absence_is_delete,
        }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uuid(value: str, *, name: str) -> str:
    try:
        canonical = str(UUID(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise SyncLedgerError(f"{name} is not a UUID") from exc
    if canonical != value:
        raise SyncLedgerError(f"{name} is not canonical")
    return canonical


def _timestamp(value: str, *, name: str) -> str:
    if not isinstance(value, str):
        raise SyncLedgerError(f"{name} is not a timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise SyncLedgerError(f"{name} is not a timestamp") from exc
    if parsed.tzinfo is None:
        raise SyncLedgerError(f"{name} must include a timezone")
    return value


def entry_snapshot(entry: Any) -> dict[str, Any]:
    return {
        "title": str(entry.title),
        "username": str(entry.username),
        "password": str(entry.password),
        "url": str(entry.url),
        "notes": str(entry.notes),
        "tags": [str(tag) for tag in entry.tags],
    }


def validate_snapshot(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != set(CONTENT_FIELDS):
        raise SyncLedgerError("Sync snapshot has an invalid schema")
    for name in CONTENT_FIELDS[:-1]:
        if not isinstance(value[name], str):
            raise SyncLedgerError(f"Sync snapshot {name} must be text")
    tags = value["tags"]
    if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
        raise SyncLedgerError("Sync snapshot tags must be text")
    return {**value, "tags": list(tags)}


def content_fingerprint(value: Any) -> str:
    snapshot = entry_snapshot(value) if not isinstance(value, dict) else validate_snapshot(value)
    encoded = json.dumps(
        snapshot,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def remote_sync_fingerprint(value: Any) -> str:
    """Fingerprint fields supported by the current external adapters.

    Tags are local Vault Unified metadata. None of the external adapters expose a
    lossless tag mapping, so including tags in remote read-back comparison creates
    false conflicts and can erase local tags during pull.
    """
    snapshot = (
        entry_snapshot(value)
        if not isinstance(value, dict)
        else validate_snapshot(value)
    )
    portable = {name: snapshot[name] for name in REMOTE_SYNC_FIELDS}
    encoded = json.dumps(
        portable,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def apply_snapshot(entry: Any, snapshot: dict[str, Any]) -> None:
    value = validate_snapshot(snapshot)
    for name in CONTENT_FIELDS:
        setattr(entry, name, list(value[name]) if name == "tags" else value[name])


@dataclass
class PendingOperation:
    operation_id: str
    kind: str
    local_revision: str
    state: str = "intent"
    created_at: str = field(default_factory=_utc_now)
    external_id: str = ""

    @classmethod
    def create(cls, kind: str, local_revision: str, external_id: str = "") -> PendingOperation:
        if kind not in OPERATION_KINDS:
            raise SyncLedgerError("Unsupported pending operation kind")
        return cls(
            operation_id=str(uuid4()),
            kind=kind,
            local_revision=_uuid(local_revision, name="local revision"),
            external_id=external_id,
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "operation_id": self.operation_id,
            "kind": self.kind,
            "local_revision": self.local_revision,
            "state": self.state,
            "created_at": self.created_at,
            "external_id": self.external_id,
        }

    @classmethod
    def from_dict(cls, value: Any) -> PendingOperation:
        if not isinstance(value, dict) or set(value) != {
            "operation_id",
            "kind",
            "local_revision",
            "state",
            "created_at",
            "external_id",
        }:
            raise SyncLedgerError("Pending operation has an invalid schema")
        if value["kind"] not in OPERATION_KINDS or value["state"] not in OPERATION_STATES:
            raise SyncLedgerError("Pending operation has an invalid state")
        if not isinstance(value["external_id"], str):
            raise SyncLedgerError("Pending operation external ID must be text")
        return cls(
            operation_id=_uuid(value["operation_id"], name="operation ID"),
            kind=value["kind"],
            local_revision=_uuid(value["local_revision"], name="local revision"),
            state=value["state"],
            created_at=_timestamp(value["created_at"], name="operation creation time"),
            external_id=value["external_id"],
        )


@dataclass
class ReplicaState:
    source: str
    external_id: str = ""
    capabilities: dict[str, bool] = field(default_factory=dict)
    remote_revision: str = ""
    base_fingerprint: str = ""
    base_snapshot: dict[str, Any] | None = None
    last_acked_local_revision: str = ""
    pending: PendingOperation | None = None
    last_operation_id: str = ""
    deletion_acknowledged: bool = False
    absence_state: str = "unknown"

    def record_base(
        self,
        entry: Any,
        *,
        remote_revision: str,
        local_revision: str,
    ) -> None:
        snapshot = entry_snapshot(entry)
        self.base_snapshot = snapshot
        self.base_fingerprint = content_fingerprint(snapshot)
        self.remote_revision = remote_revision
        self.last_acked_local_revision = local_revision
        self.absence_state = "present"
        self.deletion_acknowledged = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "external_id": self.external_id,
            "capabilities": dict(self.capabilities),
            "remote_revision": self.remote_revision,
            "base_fingerprint": self.base_fingerprint,
            "base_snapshot": self.base_snapshot,
            "last_acked_local_revision": self.last_acked_local_revision,
            "pending": self.pending.to_dict() if self.pending else None,
            "last_operation_id": self.last_operation_id,
            "deletion_acknowledged": self.deletion_acknowledged,
            "absence_state": self.absence_state,
        }

    @classmethod
    def from_dict(cls, value: Any) -> ReplicaState:
        required = {
            "source",
            "external_id",
            "capabilities",
            "remote_revision",
            "base_fingerprint",
            "base_snapshot",
            "last_acked_local_revision",
            "pending",
            "last_operation_id",
            "deletion_acknowledged",
            "absence_state",
        }
        if not isinstance(value, dict) or set(value) != required:
            raise SyncLedgerError("Replica state has an invalid schema")
        if not isinstance(value["source"], str) or not isinstance(value["external_id"], str):
            raise SyncLedgerError("Replica source and external ID must be text")
        capabilities = value["capabilities"]
        expected_caps = set(AdapterCapabilities().to_dict())
        if (
            not isinstance(capabilities, dict)
            or set(capabilities) != expected_caps
            or any(not isinstance(item, bool) for item in capabilities.values())
        ):
            raise SyncLedgerError("Replica capabilities have an invalid schema")
        fingerprint = value["base_fingerprint"]
        if not isinstance(fingerprint, str) or (
            fingerprint
            and (
                len(fingerprint) != 64
                or any(character not in "0123456789abcdef" for character in fingerprint)
            )
        ):
            raise SyncLedgerError("Replica base fingerprint is invalid")
        snapshot = value["base_snapshot"]
        if snapshot is not None:
            snapshot = validate_snapshot(snapshot)
            if content_fingerprint(snapshot) != fingerprint:
                raise SyncLedgerError("Replica base fingerprint does not match its snapshot")
        pending = value["pending"]
        if pending is not None:
            pending = PendingOperation.from_dict(pending)
        if value["absence_state"] not in {"unknown", "present", "deleted"}:
            raise SyncLedgerError("Replica absence state is invalid")
        if not isinstance(value["deletion_acknowledged"], bool):
            raise SyncLedgerError("Replica deletion acknowledgement must be boolean")
        for name in ("remote_revision", "last_acked_local_revision", "last_operation_id"):
            if not isinstance(value[name], str):
                raise SyncLedgerError(f"Replica {name} must be text")
        if value["last_acked_local_revision"]:
            _uuid(
                value["last_acked_local_revision"],
                name="last acknowledged local revision",
            )
        if value["last_operation_id"]:
            _uuid(value["last_operation_id"], name="last operation ID")
        return cls(
            source=value["source"],
            external_id=value["external_id"],
            capabilities=dict(capabilities),
            remote_revision=value["remote_revision"],
            base_fingerprint=fingerprint,
            base_snapshot=snapshot,
            last_acked_local_revision=value["last_acked_local_revision"],
            pending=pending,
            last_operation_id=value["last_operation_id"],
            deletion_acknowledged=value["deletion_acknowledged"],
            absence_state=value["absence_state"],
        )


@dataclass
class Tombstone:
    deletion_revision: str
    created_at: str
    retention_deadline: str
    required_acknowledgements: list[str]
    acknowledged: list[str] = field(default_factory=list)
    abandoned: list[str] = field(default_factory=list)

    @classmethod
    def create(cls, required: list[str], *, now: datetime | None = None) -> Tombstone:
        current = now or datetime.now(timezone.utc)
        unique = sorted(set(required))
        return cls(
            deletion_revision=str(uuid4()),
            created_at=current.isoformat(),
            retention_deadline=(
                current + timedelta(days=TOMBSTONE_RETENTION_DAYS)
            ).isoformat(),
            required_acknowledgements=unique,
        )

    def pending_sources(self) -> list[str]:
        finished = set(self.acknowledged) | set(self.abandoned)
        return [source for source in self.required_acknowledgements if source not in finished]

    def purge_ready(self, *, now: datetime | None = None) -> bool:
        current = now or datetime.now(timezone.utc)
        deadline = datetime.fromisoformat(self.retention_deadline)
        return not self.pending_sources() and current >= deadline

    def to_dict(self) -> dict[str, Any]:
        return {
            "deletion_revision": self.deletion_revision,
            "created_at": self.created_at,
            "retention_deadline": self.retention_deadline,
            "required_acknowledgements": list(self.required_acknowledgements),
            "acknowledged": list(self.acknowledged),
            "abandoned": list(self.abandoned),
        }

    @classmethod
    def from_dict(cls, value: Any) -> Tombstone:
        required = {
            "deletion_revision",
            "created_at",
            "retention_deadline",
            "required_acknowledgements",
            "acknowledged",
            "abandoned",
        }
        if not isinstance(value, dict) or set(value) != required:
            raise SyncLedgerError("Tombstone has an invalid schema")
        lists: dict[str, list[str]] = {}
        for name in ("required_acknowledgements", "acknowledged", "abandoned"):
            item = value[name]
            if not isinstance(item, list) or any(not isinstance(source, str) for source in item):
                raise SyncLedgerError(f"Tombstone {name} must contain source names")
            if len(item) != len(set(item)):
                raise SyncLedgerError(f"Tombstone {name} contains duplicates")
            lists[name] = list(item)
        known = set(lists["required_acknowledgements"])
        if not set(lists["acknowledged"]).issubset(known) or not set(
            lists["abandoned"]
        ).issubset(known):
            raise SyncLedgerError("Tombstone acknowledgement references an unknown source")
        if set(lists["acknowledged"]) & set(lists["abandoned"]):
            raise SyncLedgerError("Tombstone source cannot be acknowledged and abandoned")
        created_at = _timestamp(value["created_at"], name="tombstone creation time")
        retention_deadline = _timestamp(
            value["retention_deadline"], name="tombstone retention deadline"
        )
        if datetime.fromisoformat(retention_deadline) < datetime.fromisoformat(created_at):
            raise SyncLedgerError("Tombstone retention deadline precedes creation")
        return cls(
            deletion_revision=_uuid(value["deletion_revision"], name="deletion revision"),
            created_at=created_at,
            retention_deadline=retention_deadline,
            required_acknowledgements=lists["required_acknowledgements"],
            acknowledged=lists["acknowledged"],
            abandoned=lists["abandoned"],
        )


@dataclass
class EntrySyncLedger:
    version: int = LEDGER_VERSION
    content_revision: str = field(default_factory=lambda: str(uuid4()))
    replicas: dict[str, ReplicaState] = field(default_factory=dict)
    tombstone: Tombstone | None = None
    conflicts: dict[str, dict[str, Any]] = field(default_factory=dict)

    def new_content_revision(self) -> str:
        self.content_revision = str(uuid4())
        return self.content_revision

    def replica(
        self,
        source: str,
        external_id: str,
        capabilities: AdapterCapabilities,
    ) -> ReplicaState:
        state = self.replicas.get(source)
        if state is None:
            state = ReplicaState(source=source)
            self.replicas[source] = state
        if external_id:
            state.external_id = external_id
        state.capabilities = capabilities.to_dict()
        return state

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "content_revision": self.content_revision,
            "replicas": {
                source: replica.to_dict()
                for source, replica in sorted(self.replicas.items())
            },
            "tombstone": self.tombstone.to_dict() if self.tombstone else None,
            "conflicts": dict(self.conflicts),
        }

    @classmethod
    def from_dict(cls, value: Any) -> EntrySyncLedger:
        if value is None:
            return cls()
        if not isinstance(value, dict) or set(value) != {
            "version",
            "content_revision",
            "replicas",
            "tombstone",
            "conflicts",
        }:
            raise SyncLedgerError("Entry sync ledger has an invalid schema")
        if value["version"] != LEDGER_VERSION:
            raise SyncLedgerError("Entry sync ledger version is unsupported")
        replicas = value["replicas"]
        if not isinstance(replicas, dict) or len(replicas) > 32:
            raise SyncLedgerError("Entry sync replicas have an invalid schema")
        parsed_replicas: dict[str, ReplicaState] = {}
        for source, item in replicas.items():
            if not isinstance(source, str):
                raise SyncLedgerError("Entry sync replica source must be text")
            replica = ReplicaState.from_dict(item)
            if replica.source != source:
                raise SyncLedgerError("Entry sync replica source is inconsistent")
            parsed_replicas[source] = replica
        conflicts = value["conflicts"]
        if not isinstance(conflicts, dict) or len(conflicts) > 32:
            raise SyncLedgerError("Entry sync conflicts have an invalid schema")
        for conflict_id, conflict in conflicts.items():
            _uuid(conflict_id, name="conflict ID")
            if not isinstance(conflict, dict):
                raise SyncLedgerError("Entry sync conflict must be an object")
        tombstone = value["tombstone"]
        return cls(
            version=LEDGER_VERSION,
            content_revision=_uuid(value["content_revision"], name="content revision"),
            replicas=parsed_replicas,
            tombstone=Tombstone.from_dict(tombstone) if tombstone is not None else None,
            conflicts=dict(conflicts),
        )


def capabilities_for(adapter: Any) -> AdapterCapabilities:
    value = getattr(adapter, "capabilities", None)
    return value if isinstance(value, AdapterCapabilities) else AdapterCapabilities()

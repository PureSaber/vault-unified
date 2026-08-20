from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from vault_unified.crypto import mask_secret
from vault_unified.models import PrimarySource, SecretEntry, Source, SyncStatus
from vault_unified.sync.ledger import validate_snapshot


@dataclass
class ConflictRecord:
    id: str
    entry_id: str
    title: str
    local: SecretEntry
    remote: SecretEntry
    remote_source: Source
    default_choice: str = "local"
    base_snapshot: dict[str, Any] | None = None
    local_revision: str = ""
    remote_revision: str = ""
    remote_deleted: bool = False

    def to_dict(self, *, reveal: bool = False) -> dict:
        def side(entry: SecretEntry) -> dict:
            data = entry.to_dict()
            # Ledgers may contain other encrypted conflict snapshots. They are never a
            # conflict side and must not recurse into API or log rendering.
            data.pop("sync_ledger", None)
            if not reveal:
                data["password"] = mask_secret(entry.password, visible=0)
                if entry.notes:
                    data["notes"] = mask_secret(entry.notes, visible=0)
            return data

        base = dict(self.base_snapshot) if self.base_snapshot else None
        if base is not None and not reveal:
            base["password"] = mask_secret(str(base.get("password", "")), visible=0)
            if base.get("notes"):
                base["notes"] = mask_secret(str(base["notes"]), visible=0)
        return {
            "id": self.id,
            "entry_id": self.entry_id,
            "title": self.title,
            "remote_source": self.remote_source.value,
            "default_choice": self.default_choice,
            "local": side(self.local),
            "remote": side(self.remote),
            "base_snapshot": base,
            "local_revision": self.local_revision,
            "remote_revision": self.remote_revision,
            "remote_deleted": self.remote_deleted,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ConflictRecord:
        required = {
            "id",
            "entry_id",
            "local",
            "remote",
            "remote_source",
        }
        optional = {
            "title",
            "default_choice",
            "base_snapshot",
            "local_revision",
            "remote_revision",
            "remote_deleted",
        }
        if (
            not isinstance(data, dict)
            or not required.issubset(data)
            or not set(data).issubset(required | optional)
        ):
            raise ValueError("Conflict record has an invalid schema")
        if not isinstance(data["id"], str):
            raise ValueError("Conflict ID must be text")
        if not isinstance(data["local"], dict) or not isinstance(data["remote"], dict):
            raise ValueError("Conflict sides must be objects")
        conflict_id = str(UUID(data["id"]))
        if conflict_id != data["id"]:
            raise ValueError("Conflict ID is not canonical")
        if not isinstance(data["entry_id"], str) or not data["entry_id"]:
            raise ValueError("Conflict entry ID must be text")
        title = data.get("title", "")
        default_choice = data.get("default_choice", "local")
        local_revision = data.get("local_revision", "")
        remote_revision = data.get("remote_revision", "")
        remote_deleted = data.get("remote_deleted", False)
        if not isinstance(title, str):
            raise ValueError("Conflict title must be text")
        if default_choice not in {"local", "remote"}:
            raise ValueError("Conflict default choice is invalid")
        if not isinstance(local_revision, str) or not isinstance(remote_revision, str):
            raise ValueError("Conflict revisions must be text")
        if local_revision:
            canonical_revision = str(UUID(local_revision))
            if canonical_revision != local_revision:
                raise ValueError("Conflict local revision is not canonical")
        if not isinstance(remote_deleted, bool):
            raise ValueError("Conflict deletion state must be boolean")
        base_snapshot = data.get("base_snapshot")
        if base_snapshot is not None:
            base_snapshot = validate_snapshot(base_snapshot)
        return cls(
            id=conflict_id,
            entry_id=data["entry_id"],
            title=title,
            local=SecretEntry.from_dict(data["local"]),
            remote=SecretEntry.from_dict(data["remote"]),
            remote_source=Source(data["remote_source"]),
            default_choice=default_choice,
            base_snapshot=base_snapshot,
            local_revision=local_revision,
            remote_revision=remote_revision,
            remote_deleted=remote_deleted,
        )


def detect_conflict(local: SecretEntry, remote: SecretEntry) -> bool:
    """Return True when pull must not silently overwrite local edits."""
    if local.sync_status == SyncStatus.CONFLICT:
        return True
    if local.sync_status != SyncStatus.DIRTY:
        return False
    if not _fields_differ(local, remote):
        return False
    # Timestamped remotes: conflict only if remote changed after last sync.
    if remote.remote_updated_at and local.last_synced_at:
        return remote.remote_updated_at > local.last_synced_at
    # KeePassXC / gopass (and any source without timestamps): dirty + differ = conflict.
    return True


def _fields_differ(a: SecretEntry, b: SecretEntry) -> bool:
    return (
        a.title != b.title
        or a.username != b.username
        or a.password != b.password
        or a.url != b.url
        or a.notes != b.notes
    )


def default_resolution(primary: PrimarySource, remote_source: Source) -> str:
    if primary == PrimarySource.LOCAL:
        return "local"
    if primary.value == remote_source.value:
        return "remote"
    return "local"


def apply_resolution(
    local: SecretEntry,
    remote: SecretEntry,
    choice: str,
    merged: SecretEntry | None = None,
) -> SecretEntry:
    if choice == "remote":
        winner = remote
        winner.id = local.id
        winner.created_at = local.created_at
        winner.linked_sources = {**local.linked_sources, **remote.linked_sources}
    elif choice == "merge" and merged:
        winner = merged
        winner.id = local.id
        winner.created_at = local.created_at
        winner.linked_sources = {**local.linked_sources, **merged.linked_sources}
    else:
        winner = local
    winner.mark_synced(remote.remote_updated_at or winner.remote_updated_at)
    return winner


def new_conflict_id() -> str:
    return str(uuid4())

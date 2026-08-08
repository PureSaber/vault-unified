from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from vault_unified.crypto import mask_secret
from vault_unified.models import PrimarySource, SecretEntry, Source, SyncStatus


@dataclass
class ConflictRecord:
    id: str
    entry_id: str
    title: str
    local: SecretEntry
    remote: SecretEntry
    remote_source: Source
    default_choice: str = "local"

    def to_dict(self, *, reveal: bool = False) -> dict:
        def side(entry: SecretEntry) -> dict:
            data = entry.to_dict()
            if not reveal:
                data["password"] = mask_secret(entry.password, visible=0)
                if entry.notes:
                    data["notes"] = mask_secret(entry.notes, visible=0)
            return data

        return {
            "id": self.id,
            "entry_id": self.entry_id,
            "title": self.title,
            "remote_source": self.remote_source.value,
            "default_choice": self.default_choice,
            "local": side(self.local),
            "remote": side(self.remote),
        }

    @classmethod
    def from_dict(cls, data: dict) -> ConflictRecord:
        return cls(
            id=data["id"],
            entry_id=data["entry_id"],
            title=data.get("title", ""),
            local=SecretEntry.from_dict(data["local"]),
            remote=SecretEntry.from_dict(data["remote"]),
            remote_source=Source(data["remote_source"]),
            default_choice=data.get("default_choice", "local"),
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

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

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

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "entry_id": self.entry_id,
            "title": self.title,
            "remote_source": self.remote_source.value,
            "default_choice": self.default_choice,
            "local": self.local.to_dict(),
            "remote": self.remote.to_dict(),
        }


def detect_conflict(local: SecretEntry, remote: SecretEntry) -> bool:
    if local.sync_status == SyncStatus.DIRTY and local.last_synced_at:
        if remote.remote_updated_at and remote.remote_updated_at > local.last_synced_at:
            if _fields_differ(local, remote):
                return True
    if local.sync_status == SyncStatus.CONFLICT:
        return True
    return False


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

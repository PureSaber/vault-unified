"""Personal entry organization, independent of external-source deletion state."""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from typing import Any

from vault_unified.models import SecretEntry, SyncStatus
from vault_unified.personal_data import record_history
from vault_unified.sync.ledger import Tombstone

ORGANIZATION_KEY = "vault_unified:organization"
TRASH_RETENTION_DAYS = 30


def organization_for(entry: SecretEntry) -> dict[str, Any]:
    value = entry.source_metadata.get(ORGANIZATION_KEY, {})
    if not isinstance(value, dict):
        raise ValueError("Invalid entry organization data")
    result = {"version": 1, "state": "active", "favorite": False, "trashed_at": "", **value}
    if (type(result["version"]) is not int or result["version"] != 1
            or not isinstance(result["state"], str) or result["state"] not in {"active", "archived", "trash"}
            or not isinstance(result["favorite"], bool) or not isinstance(result["trashed_at"], str)):
        raise ValueError("Unsupported entry organization data")
    if result["state"] == "trash":
        date = datetime.fromisoformat(result["trashed_at"])
        if date.tzinfo is None:
            raise ValueError("Trash date requires a time zone")
    return copy.deepcopy(result)


def is_fillable(entry: SecretEntry) -> bool:
    return entry.sync_status != SyncStatus.DELETED_PENDING and organization_for(entry)["state"] == "active"


def expires_at(entry: SecretEntry) -> datetime | None:
    value = organization_for(entry)
    if value["state"] != "trash":
        return None
    return datetime.fromisoformat(value["trashed_at"]) + timedelta(days=TRASH_RETENTION_DAYS)


def prepare_action(entry: SecretEntry, action: str, *, tags: list[str], now: datetime | None = None) -> SecretEntry:
    candidate = copy.deepcopy(entry)
    value = organization_for(candidate)
    if candidate.sync_status == SyncStatus.DELETED_PENDING:
        raise ValueError("This entry has already been permanently removed")
    now = now or datetime.now(timezone.utc)
    if action == "purge":
        if value["state"] != "trash":
            raise ValueError("Only items in trash can be permanently removed")
        # Retain identity/link deletion acknowledgements, not credential content.
        candidate = SecretEntry(
            id=entry.id, title="", source=entry.source, external_id=entry.external_id,
            linked_sources=copy.deepcopy(entry.linked_sources),
            sync_ledger=copy.deepcopy(entry.sync_ledger), created_at=entry.created_at,
            last_synced_at=entry.last_synced_at, remote_updated_at=entry.remote_updated_at,
            proton_share_id=entry.proton_share_id,
        )
        candidate.sync_ledger.tombstone = candidate.sync_ledger.tombstone or Tombstone.create(list(entry.linked_sources))
        for replica in candidate.sync_ledger.replicas.values():
            replica.base_snapshot = None
        candidate.sync_ledger.conflicts = {}
        candidate.mark_dirty()
        candidate.sync_status = SyncStatus.DELETED_PENDING
        return candidate
    if action in {"trash", "archive"} and value["state"] == "trash":
        raise ValueError("Restore this item before archiving or deleting it again")
    if action == "trash":
        record_history(candidate)
        value.update(state="trash", trashed_at=now.isoformat())
    elif action == "archive":
        value.update(state="archived", trashed_at="")
    elif action == "restore":
        value.update(state="active", trashed_at="")
    elif action == "favorite":
        value["favorite"] = True
    elif action == "unfavorite":
        value["favorite"] = False
    elif action == "tag":
        candidate.tags = list(dict.fromkeys([*candidate.tags, *tags]))
        if len(candidate.tags) > 100:
            raise ValueError("An entry can have at most 100 tags")
    else:
        raise ValueError("Unsupported organization action")
    candidate.source_metadata[ORGANIZATION_KEY] = value
    candidate.mark_dirty()
    return candidate


def purge_expired(vault: Any, *, now: datetime | None = None) -> int:
    if vault.local.payload_version < 3:
        return 0
    now = now or datetime.now(timezone.utc)
    generation, digest = vault.local.generation, vault.local.state_digest()
    expired = [entry for entry in vault.local.list_entries() if (expires_at(entry) or datetime.max.replace(tzinfo=timezone.utc)) <= now]
    candidates = [prepare_action(entry, "purge", tags=[], now=now) for entry in expired]
    if candidates:
        vault.local.commit_import_batch(candidates, updated_entry_ids={entry.id for entry in candidates}, expected_generation=generation, expected_digest=digest)
    return len(candidates)

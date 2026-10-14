"""Project portable vault content without replicating local connector bookkeeping."""
from __future__ import annotations

import copy

from vault_unified.models import SecretEntry, SyncStatus
from vault_unified.organization import prepare_action, organization_for
from vault_unified.personal_sync.codec import ProtocolError, STATE_NAMESPACE
from vault_unified.generation_history import NAMESPACE as GENERATED_NAMESPACE, retained

LOCAL_FIELDS = {"sync_status", "sync_ledger", "last_synced_at", "remote_updated_at"}


def project(payload: dict) -> dict:
    if payload.get("version") != 3:
        raise ProtocolError("Upgrade the vault before enabling synchronization")
    objects = {"entry/" + key: {field: copy.deepcopy(value) for field, value in entry.items() if field not in LOCAL_FIELDS}
               for key, entry in payload["entries"].items() if entry.get("sync_status") != "deleted_pending"}
    objects.update({"metadata/" + key: {"data": copy.deepcopy(value)}
                    for key, value in payload.get("metadata", {}).items() if key != STATE_NAMESPACE})
    return objects


def materialize(payload: dict, objects: dict, state: dict) -> dict:
    candidate = copy.deepcopy(payload)
    original = project(payload)
    entries = candidate["entries"]
    for key, value in list(entries.items()):
        if "entry/" + key in objects or value.get("sync_status") == "deleted_pending":
            continue
        entry = SecretEntry.from_dict(value)
        if organization_for(entry)["state"] != "trash":
            entry = prepare_action(entry, "trash", tags=[])
        # Existing external connectors still need their deletion acknowledgements.
        entries[key] = prepare_action(entry, "purge", tags=[]).to_dict()
    metadata = {}
    for object_id, value in objects.items():
        kind, key = object_id.split("/", 1)
        if kind == "metadata":
            if key == STATE_NAMESPACE or set(value) != {"data"}:
                raise ProtocolError("Invalid synchronized vault metadata")
            if key == GENERATED_NAMESPACE:
                retained(value["data"])
                if any(not isinstance(item.get("id"), str) or not all(isinstance(item.get(field), str) for field in ("value", "kind", "origin"))
                       or item["kind"] not in {"password", "passphrase"} for item in value["data"]["items"]):
                    raise ProtocolError("Invalid synchronized generated-password history")
            metadata[key] = copy.deepcopy(value["data"])
        elif kind == "entry":
            if original.get(object_id) == value:
                continue
            if any(field in value for field in LOCAL_FIELDS):
                raise ProtocolError("Synchronized entry contains local connector state")
            for field in ("id", "title", "username", "password", "url", "notes", "source", "external_id", "created_at", "updated_at", "proton_share_id"):
                if not isinstance(value.get(field), str):
                    raise ProtocolError("Invalid synchronized entry text")
            if (not isinstance(value.get("tags"), list) or any(not isinstance(tag, str) for tag in value["tags"])
                    or not isinstance(value.get("linked_sources"), dict)
                    or any(not isinstance(link, str) for link in value["linked_sources"].values())
                    or not isinstance(value.get("source_metadata", {}), dict)):
                raise ProtocolError("Invalid synchronized entry metadata")
            raw = copy.deepcopy(value)
            prior = entries.get(key)
            if prior:
                raw.update({field: copy.deepcopy(prior[field]) for field in LOCAL_FIELDS if field in prior})
            entry = SecretEntry.from_dict(raw)
            if entry.id != key or set(raw) - set(entry.to_dict()):
                raise ProtocolError("Unsupported synchronized entry fields")
            entry.sync_status = SyncStatus.DIRTY
            entry.sync_ledger.new_content_revision()
            entry.sync_ledger.tombstone = None
            organization_for(entry)
            entries[key] = entry.to_dict()
        else:
            raise ProtocolError("Unsupported synchronized object")
    candidate["metadata"] = {**metadata, STATE_NAMESPACE: copy.deepcopy(state)}
    if project(candidate) != objects:
        raise ProtocolError("Synchronized data could not be preserved exactly")
    return candidate

"""Crash-safe synchronization using the vault's existing atomic transaction."""
from __future__ import annotations

import base64
from collections.abc import Callable

from vault_unified.local_store import LocalVault, EntryTransactionConflict
from vault_unified.personal_sync.codec import ProtocolError, STATE_NAMESPACE, record_identity, unseal
from vault_unified.personal_sync.merge import choose
from vault_unified.personal_sync.payload import project, materialize
from vault_unified.personal_sync.replica import queue, receive

# Bound a single network cycle. A larger space progresses over multiple cycles.
MAX_DOWNLOAD_BYTES = 128 * 1024 * 1024
MAX_DOWNLOAD_RECORDS = 1000


def download(store, state: dict, key: bytes, check: Callable[[], None]) -> tuple[dict, bool]:
    records, size = {}, 0
    pending = []
    for name in store.list():
        device, sequence = record_identity(name)
        if sequence > state["seen"].get(device, 0):
            pending.append(name)
    # Select by sequence across devices so a busy device cannot starve another
    # device's causal predecessor when a space exceeds the cycle limit.
    pending.sort(key=lambda name: (record_identity(name)[1], name))
    for name in pending:
        check()
        blob = store.get(name)
        size += len(blob)
        if records and (size > MAX_DOWNLOAD_BYTES or len(records) >= MAX_DOWNLOAD_RECORDS):
            break
        records[name] = unseal(key, state["space"], name, blob)
    return records, len(records) < len(pending)


def run(local: LocalVault, store, key: bytes, *, check: Callable[[], None] = lambda: None) -> dict:
    check()
    generation, payload = local.sync_snapshot()
    state = payload.get("metadata", {}).get(STATE_NAMESPACE)
    if not isinstance(state, dict) or "connection" not in state:
        raise ProtocolError("Connect synchronization storage first")
    label = state["connection"]["label"]
    objects = project(payload)
    queued = queue(state, objects, key, label)
    if queued != state:
        check()
        payload = materialize(payload, objects, queued)
        local.commit_sync_payload(payload, expected_generation=generation)
        generation += 1
    for name, item in queued["outbox"].items():
        check()
        store.put(name, base64.b64decode(item["ciphertext"], validate=True))
    records, more = download(store, queued, key, check)
    received, view, waiting = receive(queued, objects, records)
    if received != queued or view != objects:
        check()
        local.commit_sync_payload(materialize(payload, view, received), expected_generation=generation)
    return {"waiting": waiting, "more": more, "downloaded": len(records), "uploaded": len(queued["outbox"]), "conflicts": len(received["conflicts"])}


def resolve(local: LocalVault, key: bytes, choices: dict[str, str], *, expected_generation: int) -> None:
    generation, payload = local.sync_snapshot()
    if generation != expected_generation:
        raise EntryTransactionConflict("Vault changed after conflict review; refresh the choices")
    state = payload.get("metadata", {}).get(STATE_NAMESPACE)
    if not isinstance(state, dict) or not choices or any(key not in state["conflicts"] for key in choices):
        raise ProtocolError("Conflict choices are no longer available")
    resolved_objects = {state["conflicts"][key]["object"] for key in choices}
    required = {key for key, value in state["conflicts"].items() if value["object"] in resolved_objects}
    if set(choices) != required:
        raise ProtocolError("Choose every conflicting field for the selected entries")
    objects = project(payload)
    for conflict_id, side in choices.items():
        conflict = state["conflicts"][conflict_id]
        object_id = conflict["object"]
        # "Keep this computer" means its current value, including edits made
        # since the remote record arrived, not a stale conflict snapshot.
        if side == "local":
            continue
        candidate = choose(objects.get(object_id), conflict, side)
        if candidate is None: objects.pop(object_id, None)
        else: objects[object_id] = candidate
    queued = queue(state, objects, key, state["connection"]["label"], resolved=resolved_objects)
    # The queued event retains causal evidence; clearing the local choices now
    # prevents the user from resolving an already-confirmed offline choice twice.
    queued["conflicts"] = {key: value for key, value in queued["conflicts"].items() if key not in required}
    local.commit_sync_payload(materialize(payload, objects, queued), expected_generation=generation)

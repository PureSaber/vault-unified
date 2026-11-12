"""Crash-safe synchronization using the vault's existing atomic transaction."""
from __future__ import annotations

import base64
from collections.abc import Callable

from vault_unified.local_store import LocalVault, EntryTransactionConflict
from vault_unified.personal_sync.codec import ProtocolError, STATE_NAMESPACE, filename, record_identity, unseal
from vault_unified.personal_sync.merge import choose
from vault_unified.personal_sync.payload import project, materialize
from vault_unified.personal_sync.replica import queue, receive

# Bound a single network cycle. A larger space progresses over multiple cycles.
MAX_DOWNLOAD_BYTES = 128 * 1024 * 1024
MAX_DOWNLOAD_RECORDS = 1000


def download(store, state: dict, key: bytes, check: Callable[[], None]) -> tuple[dict, bool]:
    records, size = {}, 0
    pending, latest = set(), {}
    for name in store.list():
        device, sequence = record_identity(name)
        if sequence > state["seen"].get(device, 0):
            pending.add(name)
            latest[device] = max(sequence, latest.get(device, 0))
    # Schedule causal heads, not low sequence numbers from unrelated clocks.
    # Blocked heads count against the same page budget as their predecessors.
    # This vector is only a scheduling simulation; receive still validates and
    # applies every record before any durable seen counter can advance.
    seen = dict(state["seen"])
    stack = []
    while stack or any(seen.get(device, 0) < sequence for device, sequence in latest.items()):
        check()
        if not stack:
            device = min((device for device in latest if seen.get(device, 0) < latest[device]),
                         key=lambda device: (seen.get(device, 0), device))
            stack.append(filename(device, seen.get(device, 0) + 1))
        name = stack[-1]
        if name not in pending:
            raise ProtocolError("Synchronization history is missing required changes")
        if name not in records:
            if len(records) >= MAX_DOWNLOAD_RECORDS:
                break
            blob = store.get(name)
            size += len(blob)
            if records and size > MAX_DOWNLOAD_BYTES:
                break
            records[name] = unseal(key, state["space"], name, blob)
        record = records[name]
        missing = [(device, sequence) for device, sequence in record["context"].items()
                   if seen.get(device, 0) < sequence]
        if missing:
            device, _ = min(missing)
            predecessor = filename(device, seen.get(device, 0) + 1)
            if predecessor in stack:
                raise ProtocolError("Synchronization history contains a causal cycle")
            stack.append(predecessor)
        else:
            seen[record["device"]] = record["sequence"]
            stack.pop()
    more = any(seen.get(device, 0) < sequence for device, sequence in latest.items())
    if more and seen == state["seen"]:
        raise ProtocolError("Synchronization causal dependencies exceed the download resource limit")
    return records, more


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
    return {"waiting": waiting, "more": more, "downloaded": len(records), "uploaded": len(queued["outbox"]), "conflicts": len(received["conflicts"]), "changed": view != objects}


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

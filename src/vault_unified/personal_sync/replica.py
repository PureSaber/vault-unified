"""Pure replication state machine; callers atomically persist results with data."""
from __future__ import annotations

import base64
import copy

from vault_unified.personal_sync.codec import ProtocolError, filename, identifier, seal, validate_record
from vault_unified.personal_sync.merge import reconcile


def initial(space: str, device: str) -> dict:
    return {"version": 1, "space": identifier(space), "device": identifier(device), "next": 1,
            "seen": {}, "versions": {}, "baseline": {}, "outbox": {}, "conflicts": {},
            "tombstones": {}, "members": {}, "announced": {}, "announced_label": ""}


def covers(vector: dict, required: dict) -> bool:
    return all(vector.get(device, 0) >= sequence for device, sequence in required.items())


def queue(state: dict, objects: dict, key: bytes, label: str, *, resolved: set[str] | None = None) -> dict:
    """Durably save the returned state before sending any of its ciphertexts."""
    result = copy.deepcopy(state)
    if result.get("version") != 1 or not isinstance(label, str) or not 1 <= len(label) <= 100:
        raise ProtocolError("Invalid device replication state")
    device = identifier(result["device"])
    resolved = resolved or set()
    if any(object_id not in {item["object"] for item in result["conflicts"].values()} for object_id in resolved):
        raise ProtocolError("Conflict resolution changed after preview")

    def emit(object_id, before, after, resolution=False):
        sequence = result["next"]
        context = {**result["seen"], device: sequence - 1}
        record = {"version": 1, "space": result["space"], "device": device, "sequence": sequence,
                  "context": context, "object": object_id, "before": before, "after": after, "resolution": resolution}
        name, encrypted = seal(key, result["space"], record)
        result["outbox"][name] = {"record": copy.deepcopy(record), "ciphertext": base64.b64encode(encrypted).decode("ascii")}
        result["next"] += 1
        if not object_id.startswith("device/"):
            result["versions"].setdefault(object_id, {})[device] = sequence

    remote_seen = {member: count for member, count in result["seen"].items() if member != device}
    previous_member = result["members"].get(device)
    if result["next"] == 1 or not covers(result["announced"], remote_seen) or result["announced_label"] != label:
        emit("device/" + device, previous_member.get("value") if previous_member else None,
             {"label": label, "sequence": result["next"]})
        result["announced"] = remote_seen
        result["announced_label"] = label
    baseline = result["baseline"]
    for object_id in sorted(objects.keys() | baseline.keys() | resolved):
        before, after = baseline.get(object_id), objects.get(object_id)
        if before != after or object_id in resolved:
            emit(object_id, before, after, object_id in resolved)
    result["baseline"] = copy.deepcopy(objects)
    # Keep unresolved choices until their explicit resolution record is applied.
    return result


def receive(state: dict, objects: dict, records: dict[str, dict]) -> tuple[dict, dict, int]:
    """Return a candidate state/view plus count waiting for causal predecessors."""
    result, view = copy.deepcopy(state), copy.deepcopy(objects)
    for name, record in records.items():
        validate_record(record, result["space"], name)
    pending = {name: record for name, record in records.items()
               if record["sequence"] > result["seen"].get(record["device"], 0)}
    while pending:
        progressed = False
        for name in sorted(pending):
            record = pending[name]
            device, sequence, context, object_id = record["device"], record["sequence"], record["context"], record["object"]
            if sequence != result["seen"].get(device, 0) + 1 or not covers(result["seen"], context):
                continue
            if sequence == 1 and object_id != "device/" + device:
                raise ProtocolError("A new device must announce its identity first")
            own = device == result["device"]
            if own and (name not in result["outbox"] or result["outbox"][name]["record"] != record):
                raise ProtocolError("Device identity was reused; reconnect with a new identity")
            if object_id.startswith("device/"):
                value = record["after"]
                if not isinstance(value, dict) or set(value) != {"label", "sequence"} or not isinstance(value["label"], str) or not 1 <= len(value["label"]) <= 100 or value["sequence"] != sequence:
                    raise ProtocolError("Invalid device announcement")
                result["members"][device] = {"label": value["label"], "value": copy.deepcopy(value), "ack": {**context, device: sequence}}
            else:
                current = view.get(object_id)
                versions = result["versions"].get(object_id, {})
                causal = covers(context, versions)
                existing = [item for item in result["conflicts"].values() if item["object"] == object_id]
                resolved = record["resolution"] and causal
                if record["resolution"]:
                    # A new conflict can arrive after a user approved a choice
                    # but before its upload. Never clear that unseen conflict.
                    result["conflicts"] = {key: item for key, item in result["conflicts"].items()
                                           if item["object"] != object_id or context.get(item["device"], 0) < item["sequence"]}
                if not own:
                    if resolved or (causal and not existing):
                        candidate, conflicts = copy.deepcopy(record["after"]), []
                    elif current is None and record["after"] is not None and object_id in result["tombstones"]:
                        candidate = None
                        conflicts = [{"path": [], "kind": "delete", "base": {"present": record["before"] is not None, "value": record["before"]},
                                      "local": {"present": False}, "remote": {"present": True, "value": record["after"]}}]
                    else:
                        merged = reconcile(record["before"], current, record["after"], entry=object_id.startswith("entry/"))
                        candidate, conflicts = merged.value, merged.conflicts
                    if candidate is None: view.pop(object_id, None)
                    else: view[object_id] = candidate
                    for index, conflict in enumerate(conflicts):
                        conflict_id = f"{name}:{index}"
                        result["conflicts"][conflict_id] = {**conflict, "id": conflict_id, "object": object_id, "device": device, "sequence": sequence}
                result["versions"][object_id] = {**versions, device: max(sequence, versions.get(device, 0))}
                if record["after"] is None:
                    result["tombstones"][object_id] = {"device": device, "sequence": sequence}
            if device not in result["members"]:
                raise ProtocolError("Change author is not an announced device")
            result["members"][device]["ack"] = {**context, device: sequence}
            result["seen"][device] = sequence
            if own: result["outbox"].pop(name)
            pending.pop(name)
            progressed = True
        if not progressed:
            break
    result["baseline"] = copy.deepcopy(view)
    return result, view, len(pending)


def pending_deletions(state: dict) -> int:
    return sum(not all(member["ack"].get(item["device"], 0) >= item["sequence"]
                       for member in state["members"].values()) for item in state["tombstones"].values())

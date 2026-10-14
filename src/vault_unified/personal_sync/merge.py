"""Three-way field reconciliation. Conflicts retain all three values locally."""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from vault_unified.personal_data import PERSONAL_METADATA_KEY, MERGED_HISTORY_KEY, MAX_HISTORY_ITEMS, MAX_MERGED_HISTORY_ITEMS
from vault_unified.generation_history import NAMESPACE as GENERATED_NAMESPACE, retained

_MISSING = object()


def _clone(value):
    return _MISSING if value is _MISSING else copy.deepcopy(value)


def _present(value):
    return {"present": False} if value is _MISSING else {"present": True, "value": copy.deepcopy(value)}


@dataclass
class Reconciled:
    value: dict | None
    conflicts: list[dict]


def _state(entry):
    if entry is None:
        return "deleted"
    if entry.get("sync_status") == "deleted_pending":
        return "deleted"
    return entry.get("source_metadata", {}).get("vault_unified:organization", {}).get("state", "active")


def _history_path(path):
    return path[-3:] in [
        ("source_metadata", PERSONAL_METADATA_KEY, "history"),
        ("source_metadata", MERGED_HISTORY_KEY, "items"),
    ]


def _history_union(left, right):
    if not isinstance(left, list) or not isinstance(right, list):
        return None
    items = {}
    for item in left + right:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not isinstance(item.get("saved_at"), str):
            return None
        if item["id"] in items and items[item["id"]] != item:
            return None
        items[item["id"]] = item
    return sorted(items.values(), key=lambda item: (item["saved_at"], item["id"]), reverse=True)


def preserve_history(entry):
    """Keep the ordinary rolling window and move overflow into merged history."""
    if entry is None:
        return
    metadata = entry.get("source_metadata", {})
    personal = metadata.get(PERSONAL_METADATA_KEY)
    if not isinstance(personal, dict):
        return
    ordinary = personal.get("history", [])
    merged = metadata.get(MERGED_HISTORY_KEY, {"version": 1, "items": []})
    items = _history_union(ordinary, merged.get("items", []))
    if items is None or len(items) > MAX_HISTORY_ITEMS + MAX_MERGED_HISTORY_ITEMS:
        raise ValueError("Synchronized history cannot be preserved")
    personal["history"] = items[:MAX_HISTORY_ITEMS]
    if len(items) > MAX_HISTORY_ITEMS or MERGED_HISTORY_KEY in metadata:
        metadata[MERGED_HISTORY_KEY] = {"version": 1, "items": items[MAX_HISTORY_ITEMS:]}


def reconcile(before: dict | None, current: dict | None, incoming: dict | None, *, entry: bool = True, namespace: str = "") -> Reconciled:
    conflicts = []

    def conflict(base, ours, theirs, path, kind="field"):
        conflicts.append({"path": list(path), "kind": kind, "base": _present(base), "local": _present(ours), "remote": _present(theirs)})
        return _clone(ours)

    def merge(base: Any, ours: Any, theirs: Any, path=()):
        if ours == theirs or theirs == base:
            return _clone(ours)
        if ours == base:
            return _clone(theirs)
        if path == ("source_metadata", "vault_unified:passkeys", "credentials") and isinstance(ours, list) and isinstance(theirs, list):
            # Credentials are immutable. Merge distinct additions/removals, but
            # never synthesize one identity from independently changed keys.
            lists = [base if isinstance(base, list) else [], ours, theirs]
            if all(all(isinstance(item, dict) and isinstance(item.get("id"), str) for item in group) for group in lists):
                maps = [{item["id"]: item for item in group} for group in lists]
                if all(len(group) == len(mapping) for group, mapping in zip(lists, maps)):
                    result = []
                    for key in sorted(maps[0].keys() | maps[1].keys() | maps[2].keys()):
                        original, local, remote = [mapping.get(key, _MISSING) for mapping in maps]
                        if local == remote or remote == original: selected = local
                        elif local == original: selected = remote
                        else: return conflict(base, ours, theirs, path)
                        if selected is not _MISSING: result.append(copy.deepcopy(selected))
                    return result
            return conflict(base, ours, theirs, path)
        if _history_path(path):
            united = _history_union(ours, theirs)
            if united is not None:
                return copy.deepcopy(united)
        if not entry and namespace == GENERATED_NAMESPACE and path == ("data", "items") and isinstance(ours, list) and isinstance(theirs, list):
            combined = {}
            for item in ours + theirs:
                if not isinstance(item, dict) or not isinstance(item.get("id"), str) or (item["id"] in combined and combined[item["id"]] != item):
                    break
                combined[item["id"]] = item
            else:
                return retained({"version": 1, "items": copy.deepcopy(list(combined.values()))})["items"]
        # updated_at is bookkeeping, not a conflicting user field.
        if entry and path == ("updated_at",) and isinstance(ours, str) and isinstance(theirs, str):
            return max(ours, theirs)
        if isinstance(ours, dict) and isinstance(theirs, dict) and (isinstance(base, dict) or base is _MISSING):
            original = {} if base is _MISSING else base
            output = {}
            for key in sorted(original.keys() | ours.keys() | theirs.keys()):
                value = merge(original.get(key, _MISSING), ours.get(key, _MISSING), theirs.get(key, _MISSING), (*path, key))
                if value is not _MISSING:
                    output[key] = value
            return output
        return conflict(base, ours, theirs, path)

    # A concurrent trash/permanent-delete must be visible even if the other edit
    # only touched a different field. Never silently revive or hide that edit.
    both_changed = current != before and incoming != before and current != incoming
    deletion = current is None or incoming is None
    if entry and both_changed:
        states = {_state(current), _state(incoming)}
        deletion = deletion or (states & {"trash", "deleted"} and len(states) > 1)
    if both_changed and deletion:
        value = conflict(_MISSING if before is None else before, _MISSING if current is None else current, _MISSING if incoming is None else incoming, (), "delete")
    else:
        value = merge(_MISSING if before is None else before,
                      _MISSING if current is None else current,
                      _MISSING if incoming is None else incoming)
    if value is _MISSING:
        value = None
    if entry:
        preserve_history(value)
    return Reconciled(value, conflicts)


def choose(value: dict | None, conflict: dict, side: str) -> dict | None:
    """Apply a previously previewed field choice to a copy, not to live data."""
    if side not in {"local", "remote"}:
        raise ValueError("Choose a conflict side")
    selected = conflict[side]
    path = conflict["path"]
    if not path:
        return copy.deepcopy(selected.get("value")) if selected["present"] else None
    result = copy.deepcopy(value)
    parent = result
    for part in path[:-1]:
        if not isinstance(parent, dict):
            raise ValueError("Conflict target changed")
        parent = parent.get(part)
    if not isinstance(parent, dict):
        raise ValueError("Conflict target changed")
    if selected["present"]:
        parent[path[-1]] = copy.deepcopy(selected["value"])
    else:
        parent.pop(path[-1], None)
    return result

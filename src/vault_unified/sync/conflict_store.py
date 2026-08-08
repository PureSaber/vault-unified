from __future__ import annotations

from pathlib import Path

from vault_unified.crypto import read_encrypted_file, write_encrypted_file
from vault_unified.sync.conflicts import ConflictRecord

CONFLICTS_FILENAME = "conflicts.vault"


def conflicts_path(vault_path: Path) -> Path:
    return vault_path.parent / CONFLICTS_FILENAME


def load_conflicts(vault_path: Path, password: str) -> dict[str, ConflictRecord]:
    path = conflicts_path(vault_path)
    if not path.exists():
        return {}
    try:
        raw = read_encrypted_file(path, password)
    except Exception:
        return {}
    items = raw.get("conflicts", [])
    if not isinstance(items, list):
        return {}
    out: dict[str, ConflictRecord] = {}
    for item in items:
        try:
            rec = ConflictRecord.from_dict(item)
            out[rec.id] = rec
        except (KeyError, TypeError, ValueError):
            continue
    return out


def save_conflicts(
    vault_path: Path,
    password: str,
    conflicts: dict[str, ConflictRecord],
) -> None:
    path = conflicts_path(vault_path)
    payload = {
        "conflicts": [c.to_dict(reveal=True) for c in conflicts.values()],
    }
    write_encrypted_file(path, password, payload)

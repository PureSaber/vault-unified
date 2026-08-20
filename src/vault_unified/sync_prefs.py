from __future__ import annotations

import json
from pathlib import Path

from vault_unified.models import SyncPreferences
from vault_unified.storage import atomic_write_bytes, require_clean_storage

PREFS_FILENAME = "sync_prefs.json"


def prefs_path(vault_path: Path) -> Path:
    return vault_path.parent / PREFS_FILENAME


def load_prefs(vault_path: Path) -> SyncPreferences:
    path = prefs_path(vault_path)
    require_clean_storage(path)
    if not path.exists():
        return SyncPreferences()
    return SyncPreferences.from_dict(json.loads(path.read_text(encoding="utf-8")))


def save_prefs(vault_path: Path, prefs: SyncPreferences) -> None:
    path = prefs_path(vault_path)
    data = json.dumps(prefs.to_dict(), indent=2, ensure_ascii=False).encode("utf-8")

    def validate(candidate: bytes) -> None:
        parsed = json.loads(candidate.decode("utf-8"))
        SyncPreferences.from_dict(parsed)

    atomic_write_bytes(path, data, validator=validate)

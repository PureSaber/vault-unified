from __future__ import annotations

import json
from pathlib import Path

from vault_unified.models import SyncPreferences

PREFS_FILENAME = "sync_prefs.json"


def prefs_path(vault_path: Path) -> Path:
    return vault_path.parent / PREFS_FILENAME


def load_prefs(vault_path: Path) -> SyncPreferences:
    path = prefs_path(vault_path)
    if not path.exists():
        return SyncPreferences()
    return SyncPreferences.from_dict(json.loads(path.read_text(encoding="utf-8")))


def save_prefs(vault_path: Path, prefs: SyncPreferences) -> None:
    path = prefs_path(vault_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(prefs.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

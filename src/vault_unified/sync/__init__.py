from __future__ import annotations

from typing import Any

__all__ = [
    "ConflictRecord",
    "SyncEngine",
    "SyncResult",
    "apply_resolution",
    "default_resolution",
    "detect_conflict",
]


def __getattr__(name: str) -> Any:
    """Keep public imports lazy so the encrypted ledger can be used by models."""

    if name in {"SyncEngine", "SyncResult"}:
        from vault_unified.sync.engine import SyncEngine, SyncResult

        return {"SyncEngine": SyncEngine, "SyncResult": SyncResult}[name]
    if name in {
        "ConflictRecord",
        "apply_resolution",
        "default_resolution",
        "detect_conflict",
    }:
        from vault_unified.sync.conflicts import (
            ConflictRecord,
            apply_resolution,
            default_resolution,
            detect_conflict,
        )

        return {
            "ConflictRecord": ConflictRecord,
            "apply_resolution": apply_resolution,
            "default_resolution": default_resolution,
            "detect_conflict": detect_conflict,
        }[name]
    raise AttributeError(name)

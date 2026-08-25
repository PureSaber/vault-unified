from __future__ import annotations

import pytest

from vault_unified.backup_preview import (
    BackupPreviewExpired,
    BackupPreviewSessionMismatch,
    BackupPreviewStore,
)


def test_backup_preview_is_session_scoped_and_single_use() -> None:
    store = BackupPreviewStore(ttl_seconds=60, clock=lambda: 100.0)
    intent = store.issue(
        session_token="session-a",
        policy=(10, 30, 12),
        plan={"delete": [{"path": "synthetic", "sha256": "abc"}]},
    )

    with pytest.raises(BackupPreviewSessionMismatch):
        store.consume(intent.token, session_token="session-b")
    with pytest.raises(BackupPreviewExpired):
        store.consume(intent.token, session_token="session-a")


def test_backup_preview_expires_and_copies_plan() -> None:
    now = [100.0]
    store = BackupPreviewStore(ttl_seconds=5, clock=lambda: now[0])
    source_plan = {"delete": [{"path": "synthetic", "sha256": "abc"}]}
    intent = store.issue(
        session_token="session-a",
        policy=(0, 0, 0),
        plan=source_plan,
    )
    source_plan["delete"].clear()
    assert len(intent.plan["delete"]) == 1

    now[0] = 106.0
    with pytest.raises(BackupPreviewExpired):
        store.consume(intent.token, session_token="session-a")

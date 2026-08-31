from __future__ import annotations

import pytest

from vault_unified.restore_preview import (
    RestorePreviewExpired,
    RestorePreviewScopeMismatch,
    RestorePreviewStore,
)


def test_restore_preview_is_session_scoped_single_use_and_secret_free() -> None:
    clock = [100.0]
    store = RestorePreviewStore(ttl_seconds=30, clock=lambda: clock[0])
    intent = store.issue(
        scope="generated-session-a",
        kind="backup",
        source_path="C:/generated/backup.vault",
        source_sha256="a" * 64,
        active_sha256="b" * 64,
        active_state_digest="c" * 64,
        active_generation=7,
    )

    assert "password" not in intent.__dataclass_fields__
    assert "recovery_code" not in intent.__dataclass_fields__
    with pytest.raises(RestorePreviewScopeMismatch):
        store.consume(intent.token, scope="generated-session-b", kind="backup")
    with pytest.raises(RestorePreviewExpired):
        store.consume(intent.token, scope="generated-session-a", kind="backup")

    second = store.issue(
        scope="generated-session-a",
        kind="backup",
        source_path="C:/generated/backup.vault",
        source_sha256="a" * 64,
        active_sha256="b" * 64,
        active_state_digest="c" * 64,
        active_generation=7,
    )
    assert store.consume(second.token, scope="generated-session-a", kind="backup") == second
    with pytest.raises(RestorePreviewExpired):
        store.consume(second.token, scope="generated-session-a", kind="backup")


def test_restore_preview_expires_and_can_be_cleared_by_scope() -> None:
    clock = [10.0]
    store = RestorePreviewStore(ttl_seconds=5, clock=lambda: clock[0])
    expired = store.issue(
        scope="generated-session",
        kind="recovery_kit",
        source_path="C:/generated/kit.vault",
        source_sha256="d" * 64,
        active_sha256="e" * 64,
        active_state_digest="",
        active_generation=-1,
    )
    clock[0] = 16.0
    with pytest.raises(RestorePreviewExpired):
        store.consume(expired.token, scope="generated-session", kind="recovery_kit")

    active = store.issue(
        scope="generated-session",
        kind="recovery_kit",
        source_path="C:/generated/kit.vault",
        source_sha256="d" * 64,
        active_sha256="e" * 64,
        active_state_digest="",
        active_generation=-1,
    )
    store.clear_scope("generated-session")
    with pytest.raises(RestorePreviewExpired):
        store.consume(active.token, scope="generated-session", kind="recovery_kit")

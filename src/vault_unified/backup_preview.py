from __future__ import annotations

import copy
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable


BACKUP_PREVIEW_TTL_SECONDS = 5 * 60


class BackupPreviewError(ValueError):
    """Base error for backup cleanup confirmation failures."""


class BackupPreviewExpired(BackupPreviewError):
    """The preview token is absent, consumed, or expired."""


class BackupPreviewSessionMismatch(BackupPreviewError):
    """The preview belongs to a different unlocked session."""


@dataclass(frozen=True)
class BackupPreviewIntent:
    token: str
    session_token: str
    policy: tuple[int, int, int]
    plan: dict[str, Any]
    created_at: float
    expires_at: float


class BackupPreviewStore:
    """In-memory, single-use cleanup approvals scoped to one session."""

    def __init__(
        self,
        *,
        ttl_seconds: int = BACKUP_PREVIEW_TTL_SECONDS,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("Backup preview TTL must be positive")
        self._ttl_seconds = ttl_seconds
        self._clock = clock or time.time
        self._intents: dict[str, BackupPreviewIntent] = {}
        self._lock = threading.Lock()

    def _purge_expired(self, now: float) -> None:
        expired = [
            token
            for token, intent in self._intents.items()
            if intent.expires_at <= now
        ]
        for token in expired:
            self._intents.pop(token, None)

    def issue(
        self,
        *,
        session_token: str,
        policy: tuple[int, int, int],
        plan: dict[str, Any],
    ) -> BackupPreviewIntent:
        now = self._clock()
        token = secrets.token_urlsafe(32)
        intent = BackupPreviewIntent(
            token=token,
            session_token=session_token,
            policy=policy,
            plan=copy.deepcopy(plan),
            created_at=now,
            expires_at=now + self._ttl_seconds,
        )
        with self._lock:
            self._purge_expired(now)
            self._intents[token] = intent
        return intent

    def consume(
        self,
        token: str,
        *,
        session_token: str,
    ) -> BackupPreviewIntent:
        now = self._clock()
        with self._lock:
            self._purge_expired(now)
            intent = self._intents.pop(token, None)
        if intent is None or intent.expires_at <= now:
            raise BackupPreviewExpired(
                "Backup cleanup preview expired or was already used"
            )
        if not secrets.compare_digest(intent.session_token, session_token):
            raise BackupPreviewSessionMismatch(
                "Backup cleanup preview belongs to another unlocked session"
            )
        return intent


backup_preview_store = BackupPreviewStore()

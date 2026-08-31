from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass
from typing import Callable


RESTORE_PREVIEW_TTL_SECONDS = 5 * 60


class RestorePreviewError(ValueError):
    """Base error for a restore approval that can no longer be applied."""


class RestorePreviewExpired(RestorePreviewError):
    """The preview is missing, expired, or already consumed."""


class RestorePreviewScopeMismatch(RestorePreviewError):
    """The preview belongs to another authenticated desktop session."""


@dataclass(frozen=True)
class RestorePreviewIntent:
    token: str
    scope: str
    kind: str
    source_path: str
    source_sha256: str
    active_sha256: str
    active_state_digest: str
    active_generation: int
    created_at: float
    expires_at: float


class RestorePreviewStore:
    """In-memory, single-use restore approvals without credentials or content."""

    def __init__(
        self,
        *,
        ttl_seconds: int = RESTORE_PREVIEW_TTL_SECONDS,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("Restore preview TTL must be positive")
        self._ttl_seconds = ttl_seconds
        self._clock = clock or time.time
        self._intents: dict[str, RestorePreviewIntent] = {}
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
        scope: str,
        kind: str,
        source_path: str,
        source_sha256: str,
        active_sha256: str,
        active_state_digest: str,
        active_generation: int,
    ) -> RestorePreviewIntent:
        now = self._clock()
        intent = RestorePreviewIntent(
            token=secrets.token_urlsafe(32),
            scope=scope,
            kind=kind,
            source_path=source_path,
            source_sha256=source_sha256,
            active_sha256=active_sha256,
            active_state_digest=active_state_digest,
            active_generation=active_generation,
            created_at=now,
            expires_at=now + self._ttl_seconds,
        )
        with self._lock:
            self._purge_expired(now)
            self._intents[intent.token] = intent
        return intent

    def consume(self, token: str, *, scope: str, kind: str) -> RestorePreviewIntent:
        now = self._clock()
        with self._lock:
            self._purge_expired(now)
            intent = self._intents.pop(token, None)
        if intent is None or intent.expires_at <= now:
            raise RestorePreviewExpired("Restore preview expired or was already used")
        if not secrets.compare_digest(intent.scope, scope) or intent.kind != kind:
            raise RestorePreviewScopeMismatch(
                "Restore preview belongs to another authenticated session"
            )
        return intent

    def clear_scope(self, scope: str) -> None:
        with self._lock:
            for token in [
                token
                for token, intent in self._intents.items()
                if secrets.compare_digest(intent.scope, scope)
            ]:
                self._intents.pop(token, None)


restore_preview_store = RestorePreviewStore()

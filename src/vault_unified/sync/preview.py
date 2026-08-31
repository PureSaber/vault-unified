from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable


PREVIEW_TTL_SECONDS = 5 * 60


class SyncPreviewError(ValueError):
    """Base error for preview confirmation lifecycle failures."""


class SyncPreviewExpired(SyncPreviewError):
    """The preview token is absent, consumed, or outside its validity window."""


class SyncPreviewSessionMismatch(SyncPreviewError):
    """The preview belongs to another unlocked desktop session."""


@dataclass(frozen=True)
class SyncPreviewIntent:
    token: str
    session_token: str
    sources: tuple[str, ...]
    include_pull: bool
    include_push: bool
    local_fingerprint: str
    plan_digest: str
    operation_digest: str
    created_at: float
    expires_at: float


class SyncPreviewStore:
    """In-memory, single-use confirmation tokens scoped to one unlocked session."""

    def __init__(
        self,
        *,
        ttl_seconds: int = PREVIEW_TTL_SECONDS,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("Preview TTL must be positive")
        self._ttl_seconds = ttl_seconds
        self._clock = clock or time.time
        self._intents: dict[str, SyncPreviewIntent] = {}
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
        sources: tuple[str, ...],
        include_pull: bool,
        include_push: bool,
        local_fingerprint: str,
        plan_digest: str,
        operation_digest: str,
    ) -> SyncPreviewIntent:
        now = self._clock()
        token = secrets.token_urlsafe(32)
        intent = SyncPreviewIntent(
            token=token,
            session_token=session_token,
            sources=sources,
            include_pull=include_pull,
            include_push=include_push,
            local_fingerprint=local_fingerprint,
            plan_digest=plan_digest,
            operation_digest=operation_digest,
            created_at=now,
            expires_at=now + self._ttl_seconds,
        )
        with self._lock:
            self._purge_expired(now)
            self._intents[token] = intent
        return intent

    def consume(self, token: str, *, session_token: str) -> SyncPreviewIntent:
        now = self._clock()
        with self._lock:
            self._purge_expired(now)
            # Pop before validation so every token is single-use, including failed attempts.
            intent = self._intents.pop(token, None)
        if intent is None or intent.expires_at <= now:
            raise SyncPreviewExpired("Sync preview expired or was already used")
        if not secrets.compare_digest(intent.session_token, session_token):
            raise SyncPreviewSessionMismatch(
                "Sync preview belongs to another unlocked session"
            )
        return intent

    def clear_session(self, session_token: str) -> None:
        with self._lock:
            stale = [
                token
                for token, intent in self._intents.items()
                if secrets.compare_digest(intent.session_token, session_token)
            ]
            for token in stale:
                self._intents.pop(token, None)


def canonical_digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def sync_state_fingerprint(vault: Any) -> str:
    entries = sorted(
        (
            entry.to_dict()
            for entry in vault.local.list_entries(include_deleted=True)
        ),
        key=lambda item: item["id"],
    )
    return canonical_digest(
        {
            "vault_path": str(vault.vault_path),
            "preferences": vault.get_prefs().to_dict(),
            "entries": entries,
        }
    )


preview_store = SyncPreviewStore()

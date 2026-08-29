"""In-memory, user-mediated pairing for the optional Chromium extension.

The desktop bootstrap secret is deliberately never shared with a browser.  A
pairing code is single-use and short-lived; its resulting token is bound to
one extension origin and to the current unlocked desktop session.  Locking the
desktop vault therefore makes every browser token unusable.
"""

from __future__ import annotations

import re
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from vault_unified.session import sessions


PAIRING_TTL_SECONDS = 5 * 60
TOKEN_TTL_SECONDS = 12 * 60 * 60
_EXTENSION_ORIGIN = re.compile(r"^chrome-extension://[a-p]{32}$")


class BrowserPairingError(ValueError):
    """A browser extension pairing request is invalid or no longer active."""


@dataclass(frozen=True)
class _PendingPairing:
    session_token: str
    expires_at: float


@dataclass(frozen=True)
class _BrowserToken:
    session_token: str
    origin: str
    expires_at: float


class BrowserPairingStore:
    def __init__(self) -> None:
        self._pending: dict[str, _PendingPairing] = {}
        self._tokens: dict[str, _BrowserToken] = {}
        self._lock = threading.Lock()

    def _clean(self) -> None:
        now = time.monotonic()
        self._pending = {
            code: pair for code, pair in self._pending.items() if pair.expires_at > now
        }
        self._tokens = {
            token: pair for token, pair in self._tokens.items() if pair.expires_at > now
        }

    def issue(self, session_token: str) -> str:
        with self._lock:
            self._clean()
            # A new code deliberately invalidates any old extension connection
            # associated with this session, keeping the personal setup simple.
            self._pending = {
                code: pair
                for code, pair in self._pending.items()
                if pair.session_token != session_token
            }
            self._tokens = {
                token: pair
                for token, pair in self._tokens.items()
                if pair.session_token != session_token
            }
            code = secrets.token_urlsafe(32)
            self._pending[code] = _PendingPairing(
                session_token=session_token,
                expires_at=time.monotonic() + PAIRING_TTL_SECONDS,
            )
            return code

    @staticmethod
    def _validate_origin(origin: str) -> None:
        if not _EXTENSION_ORIGIN.fullmatch(origin):
            raise BrowserPairingError("Pairing requires a Chromium extension origin")

    def exchange(self, code: str, origin: str) -> str:
        self._validate_origin(origin)
        with self._lock:
            self._clean()
            pending = self._pending.pop(code, None)
            if pending is None:
                raise BrowserPairingError("Pairing code is invalid or has expired")
            try:
                sessions.get(pending.session_token)
            except PermissionError as exc:
                raise BrowserPairingError("Desktop vault is locked") from exc
            token = secrets.token_urlsafe(32)
            self._tokens[token] = _BrowserToken(
                session_token=pending.session_token,
                origin=origin,
                expires_at=time.monotonic() + TOKEN_TTL_SECONDS,
            )
            return token

    def vault_for(self, token: str, origin: str) -> Any:
        self._validate_origin(origin)
        with self._lock:
            self._clean()
            pair = self._tokens.get(token)
            if pair is None or not secrets.compare_digest(pair.origin, origin):
                raise BrowserPairingError("Browser pairing is invalid or has expired")
        try:
            return sessions.get(pair.session_token)
        except PermissionError as exc:
            with self._lock:
                self._tokens.pop(token, None)
            raise BrowserPairingError("Desktop vault is locked") from exc


def matches_for_url(vault: Any, requested_url: str) -> list[dict[str, str]]:
    """Return only non-secret login metadata for the active browser origin."""
    parsed = urlsplit(requested_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise BrowserPairingError("A valid http or https page is required")
    host = parsed.hostname.lower().removeprefix("www.")
    matches: list[dict[str, str]] = []
    for entry in vault.local.list_entries():
        saved = urlsplit(entry.url)
        if saved.scheme not in {"http", "https"} or not saved.hostname:
            continue
        if saved.hostname.lower().removeprefix("www.") != host:
            continue
        matches.append({"id": entry.id, "title": entry.title, "username": entry.username})
    return sorted(matches, key=lambda item: (item["title"].lower(), item["username"].lower()))


browser_pairings = BrowserPairingStore()

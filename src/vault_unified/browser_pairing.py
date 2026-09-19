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
from vault_unified.personal_data import PERSONAL_METADATA_KEY


PAIRING_TTL_SECONDS = 5 * 60
TOKEN_TTL_SECONDS = 12 * 60 * 60
_EXTENSION_ORIGIN = re.compile(r"^chrome-extension://[a-p]{32}$")


class BrowserPairingError(ValueError):
    """A browser extension pairing request is invalid or no longer active."""


class BrowserLockedError(BrowserPairingError):
    """The connection is remembered, but its vault has no unlocked session."""


@dataclass(frozen=True)
class _PendingPairing:
    session_token: str
    expires_at: float


@dataclass(frozen=True)
class _BrowserToken:
    session_token: str
    origin: str
    expires_at: float
    connection_key: str = ""


@dataclass(frozen=True)
class _BrowserConnection:
    binding: tuple[str, str, str]
    origin: str
    expires_at: float


class BrowserPairingStore:
    def __init__(self) -> None:
        self._pending: dict[str, _PendingPairing] = {}
        self._tokens: dict[str, _BrowserToken] = {}
        self._connections: dict[str, _BrowserConnection] = {}
        self._lock = threading.RLock()

    def _clean(self) -> None:
        now = time.monotonic()
        self._pending = {
            code: pair for code, pair in self._pending.items() if pair.expires_at > now
        }
        self._tokens = {
            token: pair for token, pair in self._tokens.items() if pair.expires_at > now
        }
        self._connections = {
            key: connection for key, connection in self._connections.items()
            if connection.expires_at > now
        }

    def issue(self, session_token: str) -> str:
        with self._lock:
            # A new code deliberately invalidates any old extension connection
            # associated with this vault, including remembered connections.
            self.cancel_session(session_token)
            code = secrets.token_urlsafe(32)
            self._pending[code] = _PendingPairing(
                session_token=session_token,
                expires_at=time.monotonic() + PAIRING_TTL_SECONDS,
            )
            return code

    def cancel_session(self, session_token: str, *, forget: bool = True) -> None:
        """Lock revokes access; explicit cancellation also forgets connections."""

        with self._lock:
            self._clean()
            if forget:
                try:
                    binding = sessions.browser_binding(session_token)
                except PermissionError:
                    binding = None
                keys = {
                    key for key, connection in self._connections.items()
                    if connection.binding == binding
                }
                for key in keys:
                    self._connections.pop(key, None)
                self._tokens = {
                    token: pair for token, pair in self._tokens.items()
                    if pair.connection_key not in keys
                }
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

    def clear(self) -> None:
        """Clear process-local pairing state during controlled shutdown/tests."""

        with self._lock:
            self._pending.clear()
            self._tokens.clear()
            self._connections.clear()

    @staticmethod
    def _validate_origin(origin: str) -> None:
        if not _EXTENSION_ORIGIN.fullmatch(origin):
            raise BrowserPairingError("Pairing requires a Chromium extension origin")

    def exchange(self, code: str, origin: str) -> str:
        return self.pair(code, origin)["browser_token"]

    def pair(self, code: str, origin: str, *, remember: bool = False) -> dict:
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
            connection_key = ""
            binding = sessions.browser_binding(pending.session_token)
            if remember and binding is not None:
                connection_key = secrets.token_urlsafe(32)
                self._connections[connection_key] = _BrowserConnection(
                    binding=binding, origin=origin,
                    expires_at=time.monotonic() + TOKEN_TTL_SECONDS,
                )
            self._tokens[token] = _BrowserToken(
                session_token=pending.session_token,
                origin=origin,
                expires_at=time.monotonic() + TOKEN_TTL_SECONDS,
                connection_key=connection_key,
            )
            return {"browser_token": token, "connection_key": connection_key,
                    "expires_in_seconds": TOKEN_TTL_SECONDS}

    def resume(self, connection_key: str, origin: str) -> dict:
        self._validate_origin(origin)
        with self._lock:
            self._clean()
            connection = self._connections.get(connection_key)
            if connection is None or not secrets.compare_digest(connection.origin, origin):
                raise BrowserPairingError("Browser pairing is invalid or has expired")
            try:
                session_token = sessions.browser_session(connection.binding)
            except PermissionError as exc:
                raise BrowserLockedError("Desktop vault is locked") from exc
            self._tokens = {
                token: pair for token, pair in self._tokens.items()
                if pair.connection_key != connection_key
            }
            token = secrets.token_urlsafe(32)
            self._tokens[token] = _BrowserToken(
                session_token=session_token, origin=origin,
                expires_at=connection.expires_at, connection_key=connection_key,
            )
            return {"browser_token": token}

    def disconnect(self, connection_key: str, origin: str) -> None:
        self._validate_origin(origin)
        with self._lock:
            connection = self._connections.get(connection_key)
            if connection and secrets.compare_digest(connection.origin, origin):
                self._connections.pop(connection_key, None)
                self._tokens = {
                    token: pair for token, pair in self._tokens.items()
                    if pair.connection_key != connection_key
                }

    def disconnect_token(self, token: str, origin: str) -> None:
        self._validate_origin(origin)
        with self._lock:
            pair = self._tokens.get(token)
            if pair and secrets.compare_digest(pair.origin, origin):
                self._tokens.pop(token, None)
                if pair.connection_key:
                    self.disconnect(pair.connection_key, origin)

    def vault_for(self, token: str, origin: str, *, touch: bool = True) -> Any:
        self._validate_origin(origin)
        with self._lock:
            self._clean()
            pair = self._tokens.get(token)
            if pair is None or not secrets.compare_digest(pair.origin, origin):
                raise BrowserPairingError("Browser pairing is invalid or has expired")
        try:
            return sessions.get(pair.session_token, touch=touch)
        except PermissionError as exc:
            with self._lock:
                self._tokens.pop(token, None)
            raise BrowserPairingError("Desktop vault is locked") from exc


def matches_for_url(vault: Any, requested_url: str) -> list[dict[str, str]]:
    """Return only non-secret login metadata for the active browser origin."""
    try:
        parsed = urlsplit(requested_url)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise BrowserPairingError("A valid http or https page is required") from exc
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username is not None or parsed.password is not None):
        raise BrowserPairingError("A valid http or https page is required")
    host = parsed.hostname.lower().removeprefix("www.")
    matches: list[dict[str, str]] = []
    for entry in vault.local.list_entries():
        # Matching needs only the type, not attachment decoding/history validation.
        personal = entry.source_metadata.get(PERSONAL_METADATA_KEY) or {}
        if not isinstance(personal, dict) or personal.get("entry_type", "login") != "login":
            continue
        try:
            saved = urlsplit(entry.url)
            saved_port = saved.port or (443 if saved.scheme == "https" else 80)
        except ValueError:
            continue
        if saved.scheme not in {"http", "https"} or not saved.hostname:
            continue
        if saved.hostname.lower().removeprefix("www.") != host:
            continue
        if saved.scheme != parsed.scheme or saved_port != port:
            continue
        matches.append({"id": entry.id, "title": entry.title, "username": entry.username})
    return sorted(matches, key=lambda item: (item["title"].lower(), item["username"].lower()))


browser_pairings = BrowserPairingStore()

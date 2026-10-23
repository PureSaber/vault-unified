"""Explicit desktop approval for a browser's first persistent connection.

An allowlisted extension asks to connect and shows a 6-digit code. The desktop
owner picks that code among decoys; a wrong pick denies the request. Nothing is
enrolled until the extension claims the approved result with its poll secret,
and the claim returns a device ID, never a token: access still requires the
signed ``resume`` proof from the key that never leaves the extension.

Lock order is session manager -> this store (session lock hooks call
``retain``). This store never calls the session manager or the Windows
credential store while holding its own lock.
"""
from __future__ import annotations

import hashlib
import secrets
import threading
import time
import unicodedata
from dataclasses import dataclass

from vault_unified import browser_discovery
from vault_unified.browser_trust import MAX_DEVICES, BrowserTrustError, browser_trust, validate_public_key
from vault_unified.session import sessions

CONNECT_TTL_SECONDS = 120
TERMINAL_TTL_SECONDS = 120
MAX_PENDING = 3
MAX_RECORDS = 32
RATE_LIMIT = 5
RATE_WINDOW_SECONDS = 60
REFUSAL_SECONDS = 60
CHOICES = 3
_LIVE = {"pending", "approved", "claiming"}


class BrowserConnectError(ValueError):
    """A connect request was refused; ``status`` and ``code`` describe why."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _device_name(value: str) -> str:
    # Format characters (for example bidirectional overrides) could disguise the name.
    name = "".join(char for char in (value or "") if unicodedata.category(char) != "Cf").strip() or "Browser"
    if len(name) > 64 or any(ord(char) < 32 for char in name):
        raise BrowserConnectError(422, "invalid", "Invalid browser device name")
    return name


def _allowed(origin: str) -> None:
    if origin not in browser_discovery.EXTENSION_ORIGINS:
        raise BrowserConnectError(403, "origin", "This extension cannot request a connection")


@dataclass
class _Request:
    id: str
    poll_digest: str
    code: str
    choices: list[str]
    origin: str
    public_key: str
    device_name: str
    binding: tuple[str, str, str]
    expires: float
    state: str = "pending"
    ends: float = 0.0
    device_id: str = ""


class BrowserConnectStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._requests: dict[str, _Request] = {}
        self._created: list[float] = []
        self._refuse_until = 0.0

    def _end(self, item: _Request, state: str, now: float) -> None:
        item.state = state
        item.ends = now + TERMINAL_TTL_SECONDS

    def _clean(self, now: float) -> None:
        for item in self._requests.values():
            if item.state in {"pending", "approved"} and item.expires <= now:
                self._end(item, "expired", now)
        self._requests = {key: item for key, item in self._requests.items()
                          if item.state in _LIVE or item.ends > now}
        if len(self._requests) > MAX_RECORDS:
            ended = sorted((item for item in self._requests.values() if item.state not in _LIVE), key=lambda item: item.ends)
            for item in ended[:len(self._requests) - MAX_RECORDS]:
                self._requests.pop(item.id, None)
        self._created = [stamp for stamp in self._created if stamp > now - RATE_WINDOW_SECONDS]

    def _pending(self) -> list[_Request]:
        return [item for item in self._requests.values() if item.state == "pending"]

    @staticmethod
    def _fresh_code(taken: set[str]) -> str:
        while True:
            code = f"{secrets.randbelow(10**6):06d}"
            if code not in taken:
                taken.add(code)
                return code

    def request(self, origin: str, public_key: str, device_name: str) -> dict:
        """Callers have already passed the Origin and connect-nonce checks."""
        _allowed(origin)
        try:
            validate_public_key(public_key)
        except BrowserTrustError as exc:
            raise BrowserConnectError(422, "invalid", str(exc)) from exc
        name = _device_name(device_name)
        bindings = sessions.live_browser_bindings()
        if not bindings:
            raise BrowserConnectError(423, "locked", "Desktop vault is locked")
        if bindings == {None}:
            raise BrowserConnectError(409, "upgrade_required", "Browser connections require a v3 vault")
        if len(bindings) != 1:
            raise BrowserConnectError(409, "ambiguous", "More than one vault is unlocked")
        binding = next(iter(bindings))
        with self._lock:
            # Refuse cheaply before reading the credential store.
            now = time.monotonic()
            self._clean(now)
            if now < self._refuse_until or len(self._pending()) >= MAX_PENDING or len(self._created) >= RATE_LIMIT:
                raise BrowserConnectError(429, "busy", "Too many connection requests")
        if browser_trust.device_count() >= MAX_DEVICES:
            raise BrowserConnectError(409, "device_limit", "Revoke an existing browser before adding another")
        with self._lock:
            now = time.monotonic()
            self._clean(now)
            pending = self._pending()
            if now < self._refuse_until or len(pending) >= MAX_PENDING or len(self._created) >= RATE_LIMIT:
                raise BrowserConnectError(429, "busy", "Too many connection requests")
            if any(secrets.compare_digest(item.public_key, public_key) for item in pending):
                raise BrowserConnectError(409, "duplicate", "This browser already has a pending request")
            taken = {code for item in pending for code in item.choices}
            code = self._fresh_code(taken)
            # Choices and their order are fixed per request, so repeated polls
            # cannot reveal which code stays the same.
            choices = [code] + [self._fresh_code(taken) for _ in range(CHOICES - 1)]
            secrets.SystemRandom().shuffle(choices)
            poll_secret = secrets.token_urlsafe(32)
            request_id = secrets.token_urlsafe(18)
            self._requests[request_id] = _Request(
                id=request_id, poll_digest=_digest(poll_secret), code=code, choices=choices,
                origin=origin, public_key=public_key, device_name=name, binding=binding,
                expires=now + CONNECT_TTL_SECONDS,
            )
            self._created.append(now)
            return {"request_id": request_id, "poll_secret": poll_secret, "code": code,
                    "expires_in_seconds": CONNECT_TTL_SECONDS}

    def pending_for(self, session_token: str) -> list[dict]:
        binding = sessions.browser_binding(session_token)
        with self._lock:
            now = time.monotonic()
            self._clean(now)
            return [{"id": item.id, "device_name": item.device_name, "choices": list(item.choices),
                     "remaining_seconds": max(1, int(item.expires - now))}
                    for item in self._pending() if binding is not None and item.binding == binding]

    def _owned(self, binding, request_id: str, now: float) -> _Request:
        self._clean(now)
        item = self._requests.get(request_id)
        if item is None or item.state != "pending" or binding is None or item.binding != binding:
            raise BrowserConnectError(404, "missing", "Connection request is no longer pending")
        return item

    def approve(self, session_token: str, request_id: str, code: str) -> dict:
        binding = sessions.browser_binding(session_token)
        with self._lock:
            now = time.monotonic()
            item = self._owned(binding, request_id, now)
            if not secrets.compare_digest(item.code, str(code)):
                # One attempt per request; a blind picker also waits a minute.
                self._end(item, "denied", now)
                self._refuse_until = now + REFUSAL_SECONDS
                return {"approved": False}
            item.state = "approved"
            item.expires = now + CONNECT_TTL_SECONDS
            return {"approved": True}

    def deny(self, session_token: str, request_id: str) -> None:
        binding = sessions.browser_binding(session_token)
        with self._lock:
            now = time.monotonic()
            self._end(self._owned(binding, request_id, now), "denied", now)

    def deny_all(self, session_token: str) -> int:
        binding = sessions.browser_binding(session_token)
        with self._lock:
            now = time.monotonic()
            self._clean(now)
            denied = [item for item in self._pending() if binding is not None and item.binding == binding]
            for item in denied:
                self._end(item, "denied", now)
            self._refuse_until = now + REFUSAL_SECONDS
            return len(denied)

    def status(self, origin: str, request_id: str, poll_secret: str) -> dict:
        _allowed(origin)
        with self._lock:
            now = time.monotonic()
            self._clean(now)
            item = self._requests.get(request_id)
            if (item is None or not secrets.compare_digest(item.origin, origin)
                    or not secrets.compare_digest(item.poll_digest, _digest(poll_secret or ""))):
                raise BrowserConnectError(404, "missing", "Connection request is unknown")
            if item.state in {"pending", "claiming"}:
                return {"state": "pending", "remaining_seconds": max(1, int(item.expires - now))}
            if item.state == "enrolled":
                # Re-readable until the deadline, so a lost response orphans nothing.
                return {"state": "approved", "device_id": item.device_id}
            if item.state != "approved":
                self._requests.pop(request_id, None)
                return {"state": item.state}
            item.state = "claiming"
            binding = item.binding
        return self._claim(item, binding)

    def _claim(self, item: _Request, binding: tuple[str, str, str]) -> dict:
        try:
            sessions.browser_session(binding)
        except PermissionError:
            with self._lock:
                self._end(item, "locked", time.monotonic())
            return {"state": "locked"}
        try:
            device_id = browser_trust.enroll(binding, item.origin, item.public_key, item.device_name)["id"]
        except BrowserTrustError as exc:
            with self._lock:
                self._end(item, "device_limit" if "Revoke an existing browser" in str(exc) else "failed", time.monotonic())
                return {"state": item.state}
        except Exception:
            with self._lock:
                self._end(item, "failed", time.monotonic())
            raise
        with self._lock:
            ended = item.state != "claiming"
        if ended:
            # A lock ended the request while it was being enrolled.
            try:
                browser_trust.revoke(binding, device_id)
                return {"state": "locked"}
            except BrowserTrustError:
                pass  # The device exists and cannot be removed now; hand it over instead of orphaning it.
        with self._lock:
            item.state = "enrolled"
            item.device_id = device_id
            item.ends = time.monotonic() + TERMINAL_TTL_SECONDS
        # Native host registration is left to release-build startup, so a
        # development build can never take over the installed app's host.
        return {"state": "approved", "device_id": device_id}

    def retain(self, bindings: set) -> None:
        """Session lock hook: requests for a vault that is no longer unlocked end as locked."""
        with self._lock:
            now = time.monotonic()
            for item in self._requests.values():
                if item.state in _LIVE and item.binding not in bindings:
                    self._end(item, "locked", now)

    def clear(self) -> None:
        with self._lock:
            self._requests.clear()
            self._created.clear()
            self._refuse_until = 0.0


browser_connects = BrowserConnectStore()

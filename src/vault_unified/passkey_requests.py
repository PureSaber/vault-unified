"""Session-bound website requests, approved only by the desktop owner."""
from __future__ import annotations

import copy
import secrets
import threading
import time
from dataclasses import dataclass
from uuid import UUID

from vault_unified.browser_pairing import browser_pairings, BrowserPairingError
from vault_unified.crypto import decrypt_payload
from vault_unified.local_store import EntryTransactionConflict
from vault_unified.models import SecretEntry
from vault_unified.organization import is_fillable
from vault_unified.passkeys import Request, PasskeyError, parse_request, credentials_for, register, authenticate, set_credentials
from vault_unified.personal_data import PERSONAL_METADATA_KEY
from vault_unified.session import sessions


@dataclass
class Pending:
    id: str
    scope: str
    browser: str
    extension: str
    request: Request
    expires: float
    state: str = "pending"
    attempts: int = 0
    result: dict | None = None


def _eligible(local, request):
    result = []
    for entry in local.list_entries():
        if not is_fillable(entry) or entry.source_metadata.get(PERSONAL_METADATA_KEY, {}).get("entry_type", "login") != "login":
            continue
        for credential in credentials_for(entry):
            if credential["rp_id"] == request.rp_id and (not request.credential_ids or credential["id"] in request.credential_ids):
                result.append((entry, credential))
    return result


def _backed_up(local, entry, credential):
    # Acknowledgement of an entry version by another authorized device is
    # evidence of its durable encrypted copy. A queued upload alone is not.
    from vault_unified.personal_sync.codec import STATE_NAMESPACE
    from vault_unified.personal_sync.replica import covers
    from vault_unified.passkeys import NAMESPACE
    state = local.metadata_value(STATE_NAMESPACE)
    if not isinstance(state, dict): return False
    object_id = "entry/" + entry.id
    baseline = state.get("baseline", {}).get(object_id, {})
    stored = baseline.get("source_metadata", {}).get(NAMESPACE, {}).get("credentials", [])
    version = state.get("versions", {}).get(object_id, {})
    return bool(version and credential in stored and any(
        device != state.get("device") and covers(member.get("ack", {}), version)
        for device, member in state.get("members", {}).items()))


class Requests:
    def __init__(self):
        self._guard = threading.RLock()
        self._pending: dict[str, Pending] = {}
        self._cancelled = {}

    def clear(self, scope=None):
        with self._guard:
            self._pending = {key: item for key, item in self._pending.items() if scope is not None and item.scope != scope}
            if scope is None: self._cancelled.clear()

    def _clean(self):
        self._pending = {key: item for key, item in self._pending.items() if item.expires > time.monotonic()}
        self._cancelled = {key: expiry for key, expiry in self._cancelled.items() if expiry > time.monotonic()}

    def begin(self, browser, extension, origin, operation, options, request_id=""):
        vault = browser_pairings.vault_for(browser, extension, touch=False)
        scope = browser_pairings.session_for(browser, extension)
        if vault.local.payload_version < 3:
            return {"status": "fallback"}
        request = parse_request(operation, origin, options)
        if request_id and str(UUID(request_id)) != request_id:
            raise PasskeyError("Invalid Passkey request identity")
        if operation == "get" and not _eligible(vault.local, request):
            return {"status": "fallback"}
        with self._guard:
            self._clean()
            identifier = request_id or secrets.token_urlsafe(32)
            if (browser, extension, identifier) in self._cancelled:
                raise PasskeyError("Passkey request was cancelled")
            prior = self._pending.get(identifier)
            if prior:
                if prior.browser != browser or prior.extension != extension or prior.request != request:
                    raise PasskeyError("Passkey request identity is already in use")
                return {"status": "pending", "request_id": identifier, "timeout_ms": max(1, int((prior.expires - time.monotonic()) * 1000))}
            if len(self._pending) >= 4:
                raise PasskeyError("Complete or cancel the current Passkey request")
            self._pending[identifier] = Pending(identifier, scope, browser, extension, request, time.monotonic() + request.timeout_ms / 1000)
        return {"status": "pending", "request_id": identifier, "timeout_ms": request.timeout_ms}

    def _snapshot(self, identifier):
        with self._guard:
            self._clean()
            item = self._pending.get(identifier)
            if item is None: raise PasskeyError("Passkey request expired or was cancelled")
            return item

    def _browser(self, item):
        vault = browser_pairings.vault_for(item.browser, item.extension, touch=False)
        if sessions.get(item.scope, touch=False) is not vault:
            raise BrowserPairingError("Passkey browser session changed")
        return vault

    def status(self, browser, extension, identifier):
        item = self._snapshot(identifier)
        if item.browser != browser or item.extension != extension:
            raise PasskeyError("Passkey request belongs to another browser")
        self._browser(item)
        with self._guard:
            if self._snapshot(identifier) is not item: raise PasskeyError("Passkey request changed")
            return {"status": item.state, **({"credential": copy.deepcopy(item.result)} if item.state == "complete" else {})}

    def cancel_browser(self, browser, extension, identifier):
        with self._guard:
            self._clean()
            # Cancellation can arrive before a slow begin response. Retain its
            # client-chosen identity briefly so that late delivery cannot revive it.
            self._cancelled[(browser, extension, identifier)] = time.monotonic() + 120
            if len(self._cancelled) > 256:
                self._cancelled.pop(next(iter(self._cancelled)))
            item = self._pending.get(identifier)
            if item and item.browser == browser and item.extension == extension:
                self._pending.pop(identifier)

    def reject(self, scope, identifier, *, fallback=False):
        sessions.get(scope, touch=False)
        with self._guard:
            item = self._snapshot(identifier)
            if item.scope != scope: raise PasskeyError("Passkey request belongs to another desktop session")
            if item.state == "complete": raise PasskeyError("Passkey request already completed")
            item.state = "fallback" if fallback else "cancelled"

    def list(self, scope):
        vault = sessions.get(scope, touch=False)
        with self._guard:
            self._clean()
            items = [item for item in self._pending.values() if item.scope == scope and item.state in {"pending", "verifying"}]
        result = []
        for item in items:
            try: self._browser(item)
            except (PermissionError, BrowserPairingError):
                self.cancel_browser(item.browser, item.extension, item.id)
                continue
            request = item.request
            choices = [] if request.operation == "create" else [
                {"entry_id": entry.id, "credential_id": credential["id"], "title": entry.title,
                 "user_name": credential["user_name"], "user_display_name": credential["user_display_name"]}
                for entry, credential in _eligible(vault.local, request)]
            result.append({"id": item.id, "operation": request.operation, "origin": request.origin, "rp_id": request.rp_id,
                           "user_name": request.user_name, "user_display_name": request.user_display_name,
                           "remaining_seconds": max(0, int(item.expires - time.monotonic())), "state": item.state, "choices": choices})
        return {"items": result}

    def approve(self, scope, identifier, password, *, entry_id="", credential_id=""):
        vault = sessions.get(scope, touch=False)
        item = self._snapshot(identifier)
        if item.scope != scope or self._browser(item) is not vault:
            raise PasskeyError("Passkey request belongs to another desktop session")
        with self._guard:
            if self._snapshot(identifier) is not item or item.state != "pending":
                raise PasskeyError("Passkey request is no longer waiting for approval")
            item.state = "verifying"
        try:
            generation, payload = vault.local.sync_snapshot()
            try:
                verified = decrypt_payload(password, vault.vault_path.read_bytes())
            except Exception:
                with self._guard:
                    item.attempts += 1
                    if item.attempts >= 3: item.state = "cancelled"
                raise PasskeyError("The master password could not verify this request") from None
            finally:
                password = ""
            if verified != payload:
                raise EntryTransactionConflict("Vault changed; retry the Passkey request")
            del verified
            self._browser(item)
            # Fixed lock order: session, request, local writer. No browser/keyring
            # calls or KDF work while holding the session transaction guard.
            with sessions.active(scope, vault), self._guard, vault.local._lock:
                if self._snapshot(identifier) is not item or item.state != "verifying":
                    raise PasskeyError("Passkey request was cancelled")
                if vault.local.generation != generation:
                    raise EntryTransactionConflict("Vault changed; retry the Passkey request")
                request = item.request
                if request.operation == "create":
                    existing = [credential for entry in vault.local.list_entries() for credential in credentials_for(entry)]
                    if any(credential["rp_id"] == request.rp_id and credential["id"] in request.credential_ids for credential in existing):
                        item.state = "excluded"
                        return {"approved": False, "changed": False}
                    stored, response = register(request, existing, user_verified=True)
                    candidate = SecretEntry(title=request.rp_name, username=request.user_name, url=request.origin)
                    set_credentials(candidate, [stored])
                    # Whole-payload commit binds the confirmation to its snapshot.
                    payload["entries"][candidate.id] = candidate.to_dict()
                    vault.local.commit_sync_payload(payload, expected_generation=generation)
                    changed = True
                else:
                    choice = next(((entry, credential) for entry, credential in _eligible(vault.local, request)
                                   if entry.id == entry_id and credential["id"] == credential_id), None)
                    if choice is None: raise PasskeyError("Choose an available Passkey for this website")
                    entry, credential = choice
                    response = authenticate(request, credential, user_verified=True, backed_up=_backed_up(vault.local, entry, credential))
                    changed = False
                item.result = response
                item.state = "complete"
                sessions.get(scope)
            self._browser(item)
            return {"approved": True, "changed": changed}
        finally:
            with self._guard:
                if item.state == "verifying": item.state = "pending"


requests = Requests()

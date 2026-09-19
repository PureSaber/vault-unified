"""Short-lived browser save previews; passwords stay out of preview storage/results."""
from __future__ import annotations

import copy
import secrets
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from vault_unified.browser_pairing import matches_for_url
from vault_unified.local_store import EntryTransactionConflict
from vault_unified.models import SecretEntry, Source
from vault_unified.personal_data import record_history
from vault_unified.sync.preview import canonical_digest

PREVIEW_SECONDS = 300


class BrowserSaveError(ValueError):
    """A safe, user-facing save validation failure."""


@dataclass
class _SavePreview:
    scope: str
    request_digest: str
    generation: int
    vault_digest: str
    entry_id: str
    expires_at: float
    receipt: dict | None = None


class BrowserSaveStore:
    def __init__(self) -> None:
        self._previews: dict[str, _SavePreview] = {}
        self._lock = threading.Lock()

    def clear(self) -> None:
        with self._lock:
            self._previews.clear()

    def _clean(self) -> None:
        now = time.monotonic()
        self._previews = {key: item for key, item in self._previews.items() if item.expires_at > now}

    @staticmethod
    def _candidate(vault, body: dict, *, new_id: str | None = None) -> tuple[SecretEntry, list[str]]:
        matches = matches_for_url(vault, body["url"])
        entry_id = body["entry_id"]
        if entry_id:
            if entry_id not in {item["id"] for item in matches}:
                raise BrowserSaveError("The selected account does not match this page")
            current = vault.local.get(entry_id)
            candidate = copy.deepcopy(current)
            changes = [field for field in ("title", "username", "password")
                       if getattr(current, field) != body[field]]
            if not changes:
                raise BrowserSaveError("This account already has these details")
            record_history(candidate)
        else:
            if any(item["username"] == body["username"] for item in matches):
                raise EntryTransactionConflict("An account with this username already exists; select it to update")
            parsed = urlsplit(body["url"])
            # Never persist query strings, fragments or page titles from a website.
            site = f"{parsed.scheme}://{parsed.netloc}"
            candidate = SecretEntry(title=body["title"], url=site, source=Source.LOCAL)
            if new_id:
                candidate.id = new_id
            changes = ["new_account"]
        for field in ("title", "username", "password"):
            setattr(candidate, field, body[field])
        candidate.mark_dirty()
        return candidate, changes

    def preview(self, vault, scope: str, body: dict) -> dict:
        with self._lock:
            self._clean()
            generation = vault.local.generation
            digest = vault.local.state_digest()
            candidate, changes = self._candidate(vault, body)
            if generation != vault.local.generation:
                raise EntryTransactionConflict("Vault changed; review this account again")
            # Keep one unfinished preview per browser access token and bounded receipts.
            self._previews = {key: item for key, item in self._previews.items()
                              if item.scope != scope or item.receipt is not None}
            if len(self._previews) >= 128:
                raise BrowserSaveError("Too many recent save requests; try again shortly")
            token = secrets.token_urlsafe(32)
            self._previews[token] = _SavePreview(
                scope=scope, request_digest=canonical_digest(body),
                generation=generation, vault_digest=digest, entry_id=candidate.id,
                expires_at=time.monotonic() + PREVIEW_SECONDS,
            )
            parsed = urlsplit(body["url"])
            return {
                "preview_token": token, "expires_in_seconds": PREVIEW_SECONDS,
                "action": "update" if body["entry_id"] else "create",
                "title": candidate.title, "username": candidate.username,
                "site": f"{parsed.scheme}://{parsed.netloc}", "changes": changes,
            }

    def apply(self, vault, scope: str, token: str, body: dict, *, confirmed: bool) -> dict:
        if not confirmed:
            raise BrowserSaveError("Confirm the account details before saving")
        with self._lock:
            self._clean()
            preview = self._previews.get(token)
            if preview is None or not secrets.compare_digest(preview.scope, scope):
                raise EntryTransactionConflict("Save preview expired; review this account again")
            if not secrets.compare_digest(preview.request_digest, canonical_digest(body)):
                raise EntryTransactionConflict("Account details changed after review; review them again")
            if preview.receipt is not None:
                return dict(preview.receipt)
            candidate, _ = self._candidate(vault, body, new_id=preview.entry_id)
            # Reuse the existing atomic, state-bound batch boundary for one account.
            vault.local.commit_import_batch(
                [candidate], updated_entry_ids={body["entry_id"]} if body["entry_id"] else set(),
                expected_generation=preview.generation, expected_digest=preview.vault_digest,
            )
            preview.receipt = {"saved": True, "entry_id": candidate.id}
            return dict(preview.receipt)

    def cancel(self, scope: str, token: str) -> None:
        with self._lock:
            preview = self._previews.get(token)
            if preview and secrets.compare_digest(preview.scope, scope):
                self._previews.pop(token, None)


browser_saves = BrowserSaveStore()

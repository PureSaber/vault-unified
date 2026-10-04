from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import secrets
import threading
import time
import unicodedata
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlsplit
from uuid import uuid4

from vault_unified.models import SecretEntry, Source
from vault_unified.personal_data import PERSONAL_METADATA_KEY, data_for, record_history, set_data
from vault_unified.sync.preview import canonical_digest
from vault_unified.transfer import (
    JSON_SCHEMA,
    JSON_VERSION,
    MAX_TRANSFER_BYTES,
    MAX_TRANSFER_ENTRIES,
    ImportedEntry,
    imported_entry_from_value,
    prepare_imported_entry,
)


IMPORT_PREVIEW_TTL_SECONDS = 5 * 60
SUPPORTED_FIELDS = frozenset(
    {
        "title",
        "username",
        "password",
        "url",
        "notes",
        "tags",
        "entry_type",
        "custom_fields",
        "totp_secret",
        "attachments",
    }
)


class ImportFlowError(ValueError):
    """An import preview, apply, or undo contract could not be satisfied."""


class ImportPreviewExpired(ImportFlowError):
    """A preview is absent, expired, cancelled, or already consumed."""


class ImportSessionMismatch(ImportFlowError):
    """An import operation belongs to another unlocked session."""


@dataclass(frozen=True)
class ParsedImportRow:
    preview_id: str
    index: int
    entry: ImportedEntry | None
    title: str
    username: str
    host: str
    error: str
    unsupported_fields: tuple[str, ...]
    browser_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class ImportPreviewItem:
    row: ParsedImportRow
    classification: str
    reason: str
    candidate_ids: tuple[str, ...]


@dataclass(frozen=True)
class ImportPreviewIntent:
    token: str
    session_token: str
    format: str
    source_file_digest: str
    before_vault_digest: str
    before_generation: int
    items: tuple[ImportPreviewItem, ...]
    created_at: float
    expires_at: float


@dataclass(frozen=True)
class ImportReceipt:
    transaction_id: str
    session_token: str
    source_file_digest: str
    before_vault_digest: str
    before_generation: int
    after_vault_digest: str
    after_generation: int
    added_entry_ids: tuple[str, ...]
    updated_entry_ids: tuple[str, ...]
    backup_path: str
    created_at: str
    undone: bool = False

    def public(self) -> dict[str, Any]:
        return {
            "transaction_id": self.transaction_id,
            "source_file_digest": self.source_file_digest,
            "before_vault_digest": self.before_vault_digest,
            "before_generation": self.before_generation,
            "after_vault_digest": self.after_vault_digest,
            "after_generation": self.after_generation,
            "added_entry_ids": list(self.added_entry_ids),
            "updated_entry_ids": list(self.updated_entry_ids),
            "created_at": self.created_at,
            "undone": self.undone,
        }


def _normal_text(value: str, *, casefold: bool = True) -> str:
    normalized = unicodedata.normalize("NFKC", value).replace("\r\n", "\n").replace("\r", "\n")
    normalized = " ".join(normalized.strip().split())
    return normalized.casefold() if casefold else normalized


def _exact_text(value: str) -> str:
    return unicodedata.normalize("NFC", value).replace("\r\n", "\n").replace("\r", "\n")


def _exact_url(value: str) -> str:
    candidate = unicodedata.normalize("NFC", value.strip())
    if not candidate:
        return ""
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return candidate
    if not parsed.scheme or not parsed.hostname:
        return candidate
    host = normalized_host(candidate)
    try:
        port = f":{parsed.port}" if parsed.port is not None else ""
    except ValueError:
        return candidate
    userinfo = ""
    if parsed.username is not None:
        userinfo = parsed.username
        if parsed.password is not None:
            userinfo += f":{parsed.password}"
        userinfo += "@"
    return f"{parsed.scheme.casefold()}://{userinfo}{host}{port}{parsed.path}" + (
        f"?{parsed.query}" if parsed.query else ""
    ) + (f"#{parsed.fragment}" if parsed.fragment else "")


def normalized_host(value: str) -> str:
    candidate = value.strip()
    if not candidate:
        return ""
    try:
        parsed = urlsplit(candidate if "://" in candidate else f"//{candidate}")
        host = (parsed.hostname or "").rstrip(".").casefold()
    except ValueError:
        return ""
    if not host:
        return ""
    try:
        return host.encode("idna").decode("ascii")
    except UnicodeError:
        return host


def _attachment_fingerprints(entry: SecretEntry) -> list[dict[str, Any]]:
    return sorted(
        (
            {
                "filename": _normal_text(item["filename"]),
                "mime_type": item["mime_type"].casefold(),
                "size": item["size"],
                "sha256": item["sha256"],
            }
            for item in data_for(entry)["attachments"]
        ),
        key=lambda item: (item["sha256"], item["filename"]),
    )


def secure_entry_fingerprint(entry: SecretEntry) -> str:
    personal = data_for(entry)
    return canonical_digest(
        {
            "title": _normal_text(entry.title),
            "username": _normal_text(entry.username),
            "password": entry.password,
            "url": _exact_url(entry.url),
            "notes": _exact_text(entry.notes),
            "tags": sorted({_normal_text(tag) for tag in entry.tags if tag.strip()}),
            "entry_type": personal["entry_type"],
            "custom_fields": sorted(
                (
                    {
                        "label": _normal_text(str(field["label"])),
                        "value": _exact_text(str(field["value"])),
                        "concealed": bool(field["concealed"]),
                    }
                    for field in personal["custom_fields"]
                ),
                key=lambda field: (field["label"], field["value"]),
            ),
            "totp_secret": "".join(personal["totp_secret"].split()).upper(),
            "attachments": _attachment_fingerprints(entry),
        }
    )


def _safe_text(value: Any, *, maximum: int) -> str:
    return value[:maximum] if isinstance(value, str) else ""


def _parse_value(value: Any, index: int) -> ParsedImportRow:
    preview_id = f"item-{index}"
    if not isinstance(value, dict):
        return ParsedImportRow(preview_id, index, None, "", "", "", "Entry is not an object", ())
    unsupported = tuple(sorted(str(key) for key in set(value) - SUPPORTED_FIELDS))
    title = _safe_text(value.get("title"), maximum=500).strip()
    username = _safe_text(value.get("username"), maximum=500)
    host = normalized_host(_safe_text(value.get("url"), maximum=8_192))
    if unsupported:
        return ParsedImportRow(
            preview_id,
            index,
            None,
            title,
            username,
            host,
            "Entry contains unsupported fields",
            unsupported,
        )
    try:
        imported = imported_entry_from_value(value)
        materialized = prepare_imported_entry(imported)
    except (TypeError, ValueError) as exc:
        return ParsedImportRow(preview_id, index, None, title, username, host, str(exc), ())
    return ParsedImportRow(
        preview_id,
        index,
        imported,
        materialized.title,
        materialized.username,
        normalized_host(materialized.url),
        "",
        (),
    )


def _browser_row(row: dict[str, str | None], index: int) -> ParsedImportRow:
    # Browser exports contain no trusted application metadata. Never include a
    # malformed value (or an arbitrary header) in an error or preview response.
    error = ""
    url = (row.get("url") or "").strip()
    try:
        parsed = urlsplit(url)
        valid_url = (
            parsed.scheme in {"https", "http", "android"}
            and bool(parsed.hostname)
            and not any(ord(char) < 32 for char in url)
        )
        if parsed.scheme != "android":
            valid_url = valid_url and parsed.username is None and parsed.port != 0
    except ValueError:
        valid_url = False
    if None in row or any(value is None for value in row.values()):
        error = "Browser row has missing or extra cells"
    elif not valid_url:
        error = "Browser row needs a valid website or Android app address"
    elif not row.get("password"):
        error = "Browser row has no password"
    value = {
        "title": (row.get("name") or "").strip() or normalized_host(url),
        "username": row.get("username") or "",
        "password": row.get("password") or "",
        "url": url,
        "notes": row.get("note") or row.get("notes") or "",
    }
    if error:
        # A shifted CSV record may put a password in the name/username column.
        # Do not surface any fields until the record's shape has been validated.
        return ParsedImportRow(f"item-{index}", index, None, "", "", "", error, ())
    fields = ["username", "password", "url"]
    if (row.get("name") or "").strip():
        fields.append("title")
    if "note" in row or "notes" in row:
        fields.append("notes")
    return replace(_parse_value(value, index), browser_fields=tuple(fields))


def inspect_transfer(content: str, format_name: str) -> tuple[str, tuple[ParsedImportRow, ...], str]:
    encoded = content.encode("utf-8")
    if len(encoded) > MAX_TRANSFER_BYTES:
        raise ImportFlowError("Transfer file exceeds the 10 MiB limit")
    source_digest = hashlib.sha256(encoded).hexdigest()
    content = content.removeprefix("\ufeff")
    values: list[Any]
    if format_name == "json":
        def reject_duplicate_names(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise ImportFlowError(
                        "Transfer JSON contains a duplicate field name"
                    )
                result[key] = value
            return result

        def reject_non_finite(_value: str) -> Any:
            raise ImportFlowError("Transfer JSON contains a non-finite number")

        try:
            raw = json.loads(
                content,
                object_pairs_hook=reject_duplicate_names,
                parse_constant=reject_non_finite,
            )
        except json.JSONDecodeError as exc:
            raise ImportFlowError("Transfer JSON is invalid") from exc
        if (
            not isinstance(raw, dict)
            or raw.get("schema") != JSON_SCHEMA
            or raw.get("version") != JSON_VERSION
            or not isinstance(raw.get("entries"), list)
        ):
            raise ImportFlowError("Transfer JSON has an unsupported schema")
        values = raw["entries"]
    elif format_name in {"csv", "browser_csv"}:
        try:
            reader = csv.DictReader(io.StringIO(content, newline=""), strict=True)
            if not reader.fieldnames:
                raise ImportFlowError("Transfer CSV is missing a header")
            headers = [name.strip().casefold() for name in reader.fieldnames]
            if len(headers) != len(set(headers)):
                raise ImportFlowError("Transfer CSV has duplicate column names")
            browser = format_name == "browser_csv" or (
                {"url", "username", "password"}.issubset(headers)
                and ("name" in headers or "title" not in headers)
            )
            if browser:
                if not {"url", "username", "password"}.issubset(headers):
                    raise ImportFlowError("Browser CSV needs url, username and password columns")
                if set(headers) - {"name", "url", "username", "password", "note", "notes"}:
                    raise ImportFlowError("Browser CSV contains unrecognized columns; export it again from Chrome or Edge")
                if {"note", "notes"}.issubset(headers):
                    raise ImportFlowError("Browser CSV has ambiguous note columns")
                reader.fieldnames = headers
                rows = []
                for index, row in enumerate(reader, start=1):
                    if index > MAX_TRANSFER_ENTRIES:
                        raise ImportFlowError("Transfer contains too many entries")
                    rows.append(_browser_row(row, index))
                if not rows:
                    raise ImportFlowError("Browser CSV has no password rows")
                return source_digest, tuple(rows), "chromium_csv"
            values = []
            for row in reader:
                extra_values = row.pop(None, None)
                try:
                    custom_fields: Any = json.loads(row["custom_fields"]) if row.get("custom_fields") else []
                except json.JSONDecodeError:
                    # Keep this as an item-level validation problem so one bad
                    # row cannot hide the remaining safe preview results.
                    custom_fields = {"invalid_csv_json": True}
                value: dict[str, Any] = {
                    "title": row.get("title", ""),
                    "username": row.get("username", ""),
                    "password": row.get("password", ""),
                    "url": row.get("url", ""),
                    "notes": row.get("notes", ""),
                    "tags": [tag.strip() for tag in (row.get("tags") or "").split("|") if tag.strip()],
                    "entry_type": row.get("entry_type") or "login",
                    "custom_fields": custom_fields,
                    "totp_secret": row.get("totp_secret", ""),
                    "attachments": [],
                }
                unknown = [name for name in row if name not in SUPPORTED_FIELDS and row.get(name)]
                for name in unknown:
                    value[name] = row.get(name)
                if extra_values:
                    value["extra column"] = extra_values
                values.append(value)
        except csv.Error as exc:
            raise ImportFlowError("Transfer CSV is invalid") from exc
    else:
        raise ImportFlowError("Format must be json, csv or browser_csv")
    if len(values) > MAX_TRANSFER_ENTRIES:
        raise ImportFlowError("Transfer contains too many entries")
    return (
        source_digest,
        tuple(_parse_value(value, index) for index, value in enumerate(values, start=1)),
        "vault_json" if format_name == "json" else "vault_csv",
    )


def _possible_key(entry: SecretEntry) -> tuple[tuple[str, str] | None, tuple[str, str]]:
    username = _normal_text(entry.username)
    host = normalized_host(entry.url)
    return ((host, username) if host else None, (_normal_text(entry.title), username))


def _same_browser_fields(left: SecretEntry, right: SecretEntry, fields: tuple[str, ...]) -> bool:
    for field in fields:
        first, second = getattr(left, field), getattr(right, field)
        if field in {"title", "username"}:
            first, second = _normal_text(first), _normal_text(second)
        elif field == "url":
            first, second = _exact_url(first), _exact_url(second)
        elif field == "notes":
            first, second = _exact_text(first), _exact_text(second)
        if first != second:
            return False
    return True


def build_preview(vault: Any, content: str, format_name: str) -> tuple[str, tuple[ImportPreviewItem, ...], dict[str, Any]]:
    source_digest, rows, source_format = inspect_transfer(content, format_name)
    existing = vault.local.list_entries(include_deleted=False)
    exact: dict[str, list[SecretEntry]] = {}
    possible: dict[tuple[str, str], list[SecretEntry]] = {}
    login_ids: set[str] = set()
    for entry in existing:
        exact.setdefault(secure_entry_fingerprint(entry), []).append(entry)
        personal = entry.source_metadata.get(PERSONAL_METADATA_KEY) or {}
        if isinstance(personal, dict) and personal.get("entry_type", "login") == "login":
            login_ids.add(entry.id)
        host_key, title_key = _possible_key(entry)
        if host_key:
            possible.setdefault(host_key, []).append(entry)
        possible.setdefault(title_key, []).append(entry)

    items: list[ImportPreviewItem] = []
    seen_import_fingerprints: set[str] = set()
    seen_import_keys: set[tuple[str, str]] = set()
    for row in rows:
        if row.entry is None:
            items.append(ImportPreviewItem(row, "invalid", row.error, ()))
            continue
        prepared = prepare_imported_entry(row.entry)
        fingerprint = secure_entry_fingerprint(prepared)
        host_key, title_key = _possible_key(prepared)
        candidates: dict[str, SecretEntry] = {}
        if host_key:
            candidates.update({entry.id: entry for entry in possible.get(host_key, [])})
        candidates.update({entry.id: entry for entry in possible.get(title_key, [])})
        exact_matches = exact.get(fingerprint, [])
        if row.browser_fields:
            candidates = {key: entry for key, entry in candidates.items() if key in login_ids}
            exact_matches = [entry for entry in candidates.values() if _same_browser_fields(prepared, entry, row.browser_fields)]
        if exact_matches or fingerprint in seen_import_fingerprints:
            items.append(
                ImportPreviewItem(
                    row,
                    "exact_duplicate",
                    (
                        "An identical entry already exists"
                        if exact_matches
                        else "An identical entry appears earlier in this file"
                    ),
                    tuple(sorted(entry.id for entry in exact_matches)),
                )
            )
            seen_import_fingerprints.add(fingerprint)
            continue
        matches_earlier_file_item = (
            (host_key is not None and host_key in seen_import_keys)
            or title_key in seen_import_keys
        )
        if candidates or matches_earlier_file_item:
            items.append(
                ImportPreviewItem(
                    row,
                    "possible_duplicate",
                    (
                        "The website and username, or the title and username, match"
                        if candidates
                        else "The website and username, or the title and username, match an earlier file item"
                    ),
                    tuple(sorted(candidates)),
                )
            )
        else:
            items.append(ImportPreviewItem(row, "new", "New entry", ()))
        seen_import_fingerprints.add(fingerprint)
        if host_key:
            seen_import_keys.add(host_key)
        seen_import_keys.add(title_key)

    public_items = [_public_item(vault, item) for item in items]
    attachment_count = sum(value["attachment_count"] for value in public_items)
    attachment_bytes = sum(value["attachment_bytes"] for value in public_items)
    counts = {
        "total": len(items),
        "importable": sum(item.classification in {"new", "possible_duplicate"} for item in items),
        "exact_duplicates": sum(item.classification == "exact_duplicate" for item in items),
        "possible_duplicates": sum(item.classification == "possible_duplicate" for item in items),
        "format_errors": sum(item.classification == "invalid" for item in items),
        "skipped": sum(item.classification in {"exact_duplicate", "possible_duplicate", "invalid"} for item in items),
        "add": sum(item.classification == "new" for item in items),
        "update": 0,
        "unsupported_fields": sum(len(item.row.unsupported_fields) for item in items),
        "attachments": attachment_count,
        "attachment_bytes": attachment_bytes,
    }
    return source_digest, tuple(items), {"counts": counts, "items": public_items, "source_format": source_format}


def _public_item(vault: Any, item: ImportPreviewItem) -> dict[str, Any]:
    attachments: list[dict[str, Any]] = []
    if item.row.entry is not None:
        attachments = data_for(prepare_imported_entry(item.row.entry))["attachments"]
    candidates = []
    for entry_id in item.candidate_ids:
        entry = vault.local.get(entry_id)
        if entry is not None:
            candidates.append(
                {
                    "id": entry.id,
                    "title": entry.title,
                    "username": entry.username,
                    "host": normalized_host(entry.url),
                }
            )
    return {
        "preview_id": item.row.preview_id,
        "index": item.row.index,
        "title": item.row.title,
        "username": item.row.username,
        "host": item.row.host,
        "classification": item.classification,
        "reason": item.reason,
        "default_action": "create" if item.classification == "new" else "skip",
        "candidates": candidates,
        "unsupported_fields": list(item.row.unsupported_fields),
        "attachment_count": len(attachments),
        "attachment_bytes": sum(value["size"] for value in attachments),
    }


def prepare_apply(
    vault: Any,
    intent: ImportPreviewIntent,
    decisions: Iterable[dict[str, str | None]],
) -> tuple[list[SecretEntry], list[str], list[str], int]:
    supplied: dict[str, dict[str, str | None]] = {}
    for decision in decisions:
        preview_id = str(decision.get("preview_id") or "")
        if not preview_id or preview_id in supplied:
            raise ImportFlowError("Import decisions must identify each item at most once")
        supplied[preview_id] = decision

    candidates: list[SecretEntry] = []
    added_ids: list[str] = []
    updated_ids: list[str] = []
    skipped = 0
    known_ids = {item.row.preview_id for item in intent.items}
    if set(supplied) - known_ids:
        raise ImportFlowError("Import decision references an unknown preview item")

    for item in intent.items:
        decision = supplied.get(item.row.preview_id, {})
        action = str(decision.get("action") or ("create" if item.classification == "new" else "skip"))
        target_id = str(decision.get("target_entry_id") or "")
        if item.classification in {"invalid", "exact_duplicate"}:
            if action != "skip":
                raise ImportFlowError("Invalid and identical entries can only be skipped")
            skipped += 1
            continue
        if action == "skip":
            skipped += 1
            continue
        if item.row.entry is None:
            raise ImportFlowError("Import item is not available")
        imported = prepare_imported_entry(item.row.entry)
        if action == "create":
            imported.source = Source.LOCAL
            imported.external_id = ""
            imported.linked_sources = {}
            imported.mark_dirty()
            candidates.append(imported)
            added_ids.append(imported.id)
            continue
        if action != "update" or item.classification != "possible_duplicate":
            raise ImportFlowError("Import action is not allowed for this item")
        if target_id not in item.candidate_ids:
            raise ImportFlowError("Update target is not one of the previewed matches")
        current = vault.local.get(target_id)
        if current is None:
            raise ImportFlowError("Update target changed; create a new preview")
        candidate = copy.deepcopy(current)
        record_history(candidate)
        if item.row.browser_fields:
            for field in item.row.browser_fields:
                setattr(candidate, field, getattr(imported, field))
        else:
            history = data_for(candidate)["history"]
            candidate.title = imported.title
            candidate.username = imported.username
            candidate.password = imported.password
            candidate.url = imported.url
            candidate.notes = imported.notes
            candidate.tags = list(imported.tags)
            personal = data_for(imported)
            personal["history"] = history
            set_data(candidate, personal)
        candidate.mark_dirty()
        candidates.append(candidate)
        updated_ids.append(candidate.id)
    candidate_ids = [candidate.id for candidate in candidates]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ImportFlowError(
            "Two import items cannot update the same existing entry in one batch"
        )
    return candidates, added_ids, updated_ids, skipped


class ImportFlowStore:
    """Holds plaintext previews only in memory and scopes every action to a session."""

    def __init__(
        self,
        *,
        ttl_seconds: int = IMPORT_PREVIEW_TTL_SECONDS,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("Preview TTL must be positive")
        self._ttl_seconds = ttl_seconds
        self._clock = clock or time.time
        self._intents: dict[str, ImportPreviewIntent] = {}
        self._receipts: dict[str, ImportReceipt] = {}
        self._lock = threading.Lock()

    def _purge_expired(self, now: float) -> None:
        for token in [key for key, value in self._intents.items() if value.expires_at <= now]:
            self._intents.pop(token, None)

    def issue(
        self,
        *,
        session_token: str,
        format_name: str,
        source_file_digest: str,
        before_vault_digest: str,
        before_generation: int,
        items: tuple[ImportPreviewItem, ...],
    ) -> ImportPreviewIntent:
        now = self._clock()
        intent = ImportPreviewIntent(
            token=secrets.token_urlsafe(32),
            session_token=session_token,
            format=format_name,
            source_file_digest=source_file_digest,
            before_vault_digest=before_vault_digest,
            before_generation=before_generation,
            items=copy.deepcopy(items),
            created_at=now,
            expires_at=now + self._ttl_seconds,
        )
        with self._lock:
            self._purge_expired(now)
            self._intents[intent.token] = intent
        return intent

    def consume(self, token: str, *, session_token: str) -> ImportPreviewIntent:
        now = self._clock()
        with self._lock:
            self._purge_expired(now)
            intent = self._intents.pop(token, None)
        if intent is None or intent.expires_at <= now:
            raise ImportPreviewExpired("Import preview expired, was cancelled, or was already used")
        if not secrets.compare_digest(intent.session_token, session_token):
            raise ImportSessionMismatch("Import preview belongs to another unlocked session")
        return intent

    def cancel(self, token: str, *, session_token: str) -> None:
        self.consume(token, session_token=session_token)

    def add_receipt(self, receipt: ImportReceipt) -> None:
        with self._lock:
            self._receipts[receipt.transaction_id] = receipt

    def receipt(self, transaction_id: str, *, session_token: str) -> ImportReceipt:
        with self._lock:
            receipt = self._receipts.get(transaction_id)
        if receipt is None:
            raise ImportFlowError("Import receipt was not found in this unlocked session")
        if not secrets.compare_digest(receipt.session_token, session_token):
            raise ImportSessionMismatch("Import receipt belongs to another unlocked session")
        return receipt

    def mark_undone(self, transaction_id: str, *, session_token: str) -> ImportReceipt:
        receipt = self.receipt(transaction_id, session_token=session_token)
        updated = replace(receipt, undone=True)
        with self._lock:
            self._receipts[transaction_id] = updated
        return updated

    def clear_session(self, session_token: str) -> None:
        with self._lock:
            self._intents = {
                token: intent
                for token, intent in self._intents.items()
                if not secrets.compare_digest(intent.session_token, session_token)
            }
            self._receipts = {
                token: receipt
                for token, receipt in self._receipts.items()
                if not secrets.compare_digest(receipt.session_token, session_token)
            }


def new_receipt(
    *,
    session_token: str,
    intent: ImportPreviewIntent,
    after_vault_digest: str,
    after_generation: int,
    added_ids: list[str],
    updated_ids: list[str],
    backup_path: str,
) -> ImportReceipt:
    return ImportReceipt(
        transaction_id=str(uuid4()),
        session_token=session_token,
        source_file_digest=intent.source_file_digest,
        before_vault_digest=intent.before_vault_digest,
        before_generation=intent.before_generation,
        after_vault_digest=after_vault_digest,
        after_generation=after_generation,
        added_entry_ids=tuple(added_ids),
        updated_entry_ids=tuple(updated_ids),
        backup_path=backup_path,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


import_flow_store = ImportFlowStore()

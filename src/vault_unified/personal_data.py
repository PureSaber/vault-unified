"""Encrypted, personal-only extensions for Vault Unified entries.

The portable ``SecretEntry`` model intentionally remains small because it is
shared with several password-manager CLIs.  Personal-only fields therefore
live in a namespaced ``source_metadata`` value.  They are encrypted with the
entry, excluded from remote fingerprints, and survive an older client that
round-trips unknown source metadata.
"""

from __future__ import annotations

import base64
import copy
import hashlib
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


PERSONAL_METADATA_KEY = "vault_unified:personal"
PERSONAL_SCHEMA_VERSION = 1
ENTRY_TYPES = frozenset({"login", "secure_note", "card", "identity", "ssh_key", "recovery_code"})
MAX_CUSTOM_FIELDS = 32
MAX_CUSTOM_FIELD_LABEL = 120
MAX_CUSTOM_FIELD_VALUE = 16_384
MAX_ATTACHMENTS = 10
MAX_ATTACHMENT_BYTES = 1_048_576
MAX_TOTAL_ATTACHMENT_BYTES = 5 * MAX_ATTACHMENT_BYTES
MAX_HISTORY_ITEMS = 20


class PersonalDataError(ValueError):
    """A personal-only entry extension is malformed or exceeds a safe limit."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty() -> dict[str, Any]:
    return {
        "version": PERSONAL_SCHEMA_VERSION,
        "entry_type": "login",
        "custom_fields": [],
        "totp_secret": "",
        "attachments": [],
        "history": [],
    }


def _text(value: Any, *, name: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise PersonalDataError(f"{name} must be text")
    if len(value) > maximum:
        raise PersonalDataError(f"{name} is too long")
    return value


def normalize_custom_fields(value: Any) -> list[dict[str, str | bool]]:
    if value in (None, []):
        return []
    if not isinstance(value, list) or len(value) > MAX_CUSTOM_FIELDS:
        raise PersonalDataError("custom_fields must contain at most 32 fields")
    result: list[dict[str, str | bool]] = []
    for item in value:
        if not isinstance(item, dict) or set(item) - {"label", "value", "concealed"}:
            raise PersonalDataError("custom field has an invalid shape")
        label = _text(item.get("label", ""), name="custom field label", maximum=MAX_CUSTOM_FIELD_LABEL).strip()
        if not label:
            raise PersonalDataError("custom field label is required")
        field_value = _text(item.get("value", ""), name="custom field value", maximum=MAX_CUSTOM_FIELD_VALUE)
        concealed = item.get("concealed", False)
        if not isinstance(concealed, bool):
            raise PersonalDataError("custom field concealed must be true or false")
        result.append({"label": label, "value": field_value, "concealed": concealed})
    return result


def _normalize_attachment(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"id", "filename", "mime_type", "size", "sha256", "data_b64"}:
        raise PersonalDataError("attachment has an invalid shape")
    attachment_id = _text(value["id"], name="attachment id", maximum=64)
    filename = _text(value["filename"], name="attachment filename", maximum=255).strip()
    mime_type = _text(value["mime_type"], name="attachment mime type", maximum=255).strip()
    if not attachment_id or not filename or not mime_type:
        raise PersonalDataError("attachment metadata is required")
    size = value["size"]
    if isinstance(size, bool) or not isinstance(size, int) or size < 0 or size > MAX_ATTACHMENT_BYTES:
        raise PersonalDataError("attachment size is invalid")
    digest = _text(value["sha256"], name="attachment sha256", maximum=64)
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise PersonalDataError("attachment sha256 is invalid")
    encoded = _text(value["data_b64"], name="attachment data", maximum=((MAX_ATTACHMENT_BYTES + 2) // 3) * 4 + 8)
    try:
        raw = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise PersonalDataError("attachment data is not base64") from exc
    if len(raw) != size or hashlib.sha256(raw).hexdigest() != digest:
        raise PersonalDataError("attachment data integrity check failed")
    return {
        "id": attachment_id,
        "filename": filename,
        "mime_type": mime_type,
        "size": size,
        "sha256": digest,
        "data_b64": encoded,
    }


def _normalize_history(value: Any) -> list[dict[str, Any]]:
    if value in (None, []):
        return []
    if not isinstance(value, list) or len(value) > MAX_HISTORY_ITEMS:
        raise PersonalDataError("history has too many items")
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {"id", "saved_at", "snapshot"}:
            raise PersonalDataError("history item has an invalid shape")
        if not isinstance(item["id"], str) or not isinstance(item["saved_at"], str) or not isinstance(item["snapshot"], dict):
            raise PersonalDataError("history item is invalid")
        result.append(copy.deepcopy(item))
    return result


def _normalize(value: Any) -> dict[str, Any]:
    if value in (None, {}):
        return _empty()
    if not isinstance(value, dict) or set(value) != set(_empty()):
        raise PersonalDataError("personal entry data has an invalid schema")
    if value.get("version") != PERSONAL_SCHEMA_VERSION:
        raise PersonalDataError("personal entry data has an unsupported schema")
    entry_type = value.get("entry_type")
    if entry_type not in ENTRY_TYPES:
        raise PersonalDataError("entry type is unsupported")
    attachments = [_normalize_attachment(item) for item in value.get("attachments", [])]
    if len(attachments) > MAX_ATTACHMENTS:
        raise PersonalDataError("entry has too many attachments")
    if sum(item["size"] for item in attachments) > MAX_TOTAL_ATTACHMENT_BYTES:
        raise PersonalDataError("entry attachments are too large")
    return {
        "version": PERSONAL_SCHEMA_VERSION,
        "entry_type": entry_type,
        "custom_fields": normalize_custom_fields(value.get("custom_fields")),
        "totp_secret": _text(value.get("totp_secret", ""), name="TOTP secret", maximum=1024),
        "attachments": attachments,
        "history": _normalize_history(value.get("history")),
    }


def data_for(entry: Any) -> dict[str, Any]:
    """Return a normalized copy of the entry's personal-only data."""
    metadata = getattr(entry, "source_metadata", {})
    return _normalize(metadata.get(PERSONAL_METADATA_KEY))


def set_data(entry: Any, value: dict[str, Any]) -> None:
    normalized = _normalize(value)
    metadata = dict(getattr(entry, "source_metadata", {}) or {})
    if normalized == _empty():
        metadata.pop(PERSONAL_METADATA_KEY, None)
    else:
        metadata[PERSONAL_METADATA_KEY] = normalized
    entry.source_metadata = metadata


def update_data(
    entry: Any,
    *,
    entry_type: str | None = None,
    custom_fields: list[dict[str, Any]] | None = None,
    totp_secret: str | None = None,
) -> dict[str, Any]:
    value = data_for(entry)
    if entry_type is not None:
        if entry_type not in ENTRY_TYPES:
            raise PersonalDataError("entry type is unsupported")
        value["entry_type"] = entry_type
    if custom_fields is not None:
        value["custom_fields"] = normalize_custom_fields(custom_fields)
    if totp_secret is not None:
        value["totp_secret"] = _text(totp_secret, name="TOTP secret", maximum=1024)
    set_data(entry, value)
    return data_for(entry)


def add_attachment(
    entry: Any,
    *,
    filename: str,
    mime_type: str,
    data_b64: str,
) -> dict[str, Any]:
    value = data_for(entry)
    if len(value["attachments"]) >= MAX_ATTACHMENTS:
        raise PersonalDataError("entry already has the maximum number of attachments")
    filename = _text(filename, name="attachment filename", maximum=255).strip()
    mime_type = _text(mime_type, name="attachment mime type", maximum=255).strip()
    if not filename or not mime_type:
        raise PersonalDataError("attachment filename and mime type are required")
    try:
        raw = base64.b64decode(data_b64, validate=True)
    except Exception as exc:
        raise PersonalDataError("attachment data is not base64") from exc
    if len(raw) > MAX_ATTACHMENT_BYTES:
        raise PersonalDataError("attachment exceeds the 1 MiB limit")
    if sum(item["size"] for item in value["attachments"]) + len(raw) > MAX_TOTAL_ATTACHMENT_BYTES:
        raise PersonalDataError("entry attachments exceed the 5 MiB limit")
    attachment = {
        "id": str(uuid4()),
        "filename": filename,
        "mime_type": mime_type,
        "size": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "data_b64": base64.b64encode(raw).decode("ascii"),
    }
    value["attachments"].append(attachment)
    set_data(entry, value)
    return attachment_public(attachment)


def attachment_public(value: dict[str, Any]) -> dict[str, Any]:
    return {key: value[key] for key in ("id", "filename", "mime_type", "size", "sha256")}


def get_attachment(entry: Any, attachment_id: str) -> dict[str, Any]:
    for attachment in data_for(entry)["attachments"]:
        if attachment["id"] == attachment_id:
            return attachment
    raise KeyError("attachment not found")


def delete_attachment(entry: Any, attachment_id: str) -> bool:
    value = data_for(entry)
    before = len(value["attachments"])
    value["attachments"] = [item for item in value["attachments"] if item["id"] != attachment_id]
    if len(value["attachments"]) == before:
        return False
    set_data(entry, value)
    return True


def snapshot(entry: Any) -> dict[str, Any]:
    """Capture restorable fields without duplicating attachment binary data."""
    value = data_for(entry)
    return {
        "title": str(entry.title),
        "username": str(entry.username),
        "password": str(entry.password),
        "url": str(entry.url),
        "notes": str(entry.notes),
        "tags": list(entry.tags),
        "entry_type": value["entry_type"],
        "custom_fields": copy.deepcopy(value["custom_fields"]),
        "totp_secret": value["totp_secret"],
        "attachment_ids": [item["id"] for item in value["attachments"]],
    }


def record_history(entry: Any) -> None:
    value = data_for(entry)
    value["history"].insert(
        0,
        {"id": str(uuid4()), "saved_at": _utc_now(), "snapshot": snapshot(entry)},
    )
    value["history"] = value["history"][:MAX_HISTORY_ITEMS]
    set_data(entry, value)


def list_history(entry: Any, *, reveal: bool = False) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in data_for(entry)["history"]:
        snapshot_value = copy.deepcopy(item["snapshot"])
        if not reveal:
            snapshot_value["password"] = ""
            snapshot_value["totp_secret"] = ""
            snapshot_value["custom_fields"] = [
                {**field, "value": ""} for field in snapshot_value["custom_fields"]
            ]
        result.append({"id": item["id"], "saved_at": item["saved_at"], "snapshot": snapshot_value})
    return result


def restore_history(entry: Any, history_id: str) -> None:
    value = data_for(entry)
    selected = next((item for item in value["history"] if item["id"] == history_id), None)
    if selected is None:
        raise KeyError("history version not found")
    record_history(entry)
    current = data_for(entry)
    snap = selected["snapshot"]
    entry.title = snap["title"]
    entry.username = snap["username"]
    entry.password = snap["password"]
    entry.url = snap["url"]
    entry.notes = snap["notes"]
    entry.tags = list(snap["tags"])
    current["entry_type"] = snap["entry_type"]
    current["custom_fields"] = copy.deepcopy(snap["custom_fields"])
    current["totp_secret"] = snap["totp_secret"]
    # Attachments are deliberately not resurrected: their binary data is not
    # duplicated in history.  Existing attachments remain available.
    set_data(entry, current)


def public_data(entry: Any, *, reveal: bool) -> dict[str, Any]:
    value = data_for(entry)
    return {
        "entry_type": value["entry_type"],
        "custom_fields": copy.deepcopy(value["custom_fields"]) if reveal else [
            {**field, "value": ""} for field in value["custom_fields"]
        ],
        "totp_secret": value["totp_secret"] if reveal else "",
        "has_totp_secret": bool(value["totp_secret"]),
        "attachments": [attachment_public(item) for item in value["attachments"]],
        "history_count": len(value["history"]),
    }


def merge_personal_metadata(existing: dict[str, Any] | None, incoming: dict[str, Any] | None) -> dict[str, Any]:
    """Keep local-only fields when a remote adapter refreshes its metadata."""
    result = copy.deepcopy(incoming or {})
    personal = (existing or {}).get(PERSONAL_METADATA_KEY)
    if personal is not None:
        result[PERSONAL_METADATA_KEY] = copy.deepcopy(personal)
    return result

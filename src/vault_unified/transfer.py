"""Explicit, user-confirmed plaintext import and export helpers."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from typing import Any

from vault_unified.models import SecretEntry
from vault_unified.personal_data import PersonalDataError, data_for, set_data, update_data


MAX_TRANSFER_BYTES = 10 * 1024 * 1024
MAX_TRANSFER_ENTRIES = 5_000
JSON_SCHEMA = "vault-unified-transfer"
JSON_VERSION = 1


@dataclass(frozen=True)
class ImportedEntry:
    title: str
    username: str
    password: str
    url: str
    notes: str
    tags: list[str]
    entry_type: str
    custom_fields: list[dict[str, Any]]
    totp_secret: str
    attachments: list[dict[str, Any]]


def _text(value: Any, *, name: str, maximum: int = 100_000) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be text")
    if len(value) > maximum:
        raise ValueError(f"{name} is too long")
    return value


def _tags(value: Any) -> list[str]:
    if value in (None, "", []):
        return []
    if not isinstance(value, list) or len(value) > 100 or any(not isinstance(item, str) for item in value):
        raise ValueError("tags must be a list of text values")
    return [item.strip() for item in value if item.strip()]


def _entry_from_json(value: Any) -> ImportedEntry:
    if not isinstance(value, dict):
        raise ValueError("transfer entry must be an object")
    allowed = {
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
    if set(value) - allowed:
        raise ValueError("transfer entry contains an unknown field")
    title = _text(value.get("title", ""), name="title", maximum=500).strip()
    if not title:
        raise ValueError("transfer entry title is required")
    return ImportedEntry(
        title=title,
        username=_text(value.get("username", ""), name="username"),
        password=_text(value.get("password", ""), name="password"),
        url=_text(value.get("url", ""), name="url"),
        notes=_text(value.get("notes", ""), name="notes"),
        tags=_tags(value.get("tags", [])),
        entry_type=_text(value.get("entry_type", "login"), name="entry type", maximum=64),
        custom_fields=value.get("custom_fields", []),
        totp_secret=_text(value.get("totp_secret", ""), name="TOTP secret", maximum=1024),
        attachments=value.get("attachments", []),
    )


def parse_transfer(text: str, format_name: str) -> list[ImportedEntry]:
    if len(text.encode("utf-8")) > MAX_TRANSFER_BYTES:
        raise ValueError("transfer file exceeds the 10 MiB limit")
    if format_name == "json":
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("transfer JSON is invalid") from exc
        if (
            not isinstance(raw, dict)
            or raw.get("schema") != JSON_SCHEMA
            or raw.get("version") != JSON_VERSION
            or not isinstance(raw.get("entries"), list)
        ):
            raise ValueError("transfer JSON has an unsupported schema")
        values = raw["entries"]
    elif format_name == "csv":
        try:
            rows = list(csv.DictReader(io.StringIO(text)))
        except csv.Error as exc:
            raise ValueError("transfer CSV is invalid") from exc
        values = []
        for row in rows:
            values.append(
                {
                    "title": row.get("title", ""),
                    "username": row.get("username", ""),
                    "password": row.get("password", ""),
                    "url": row.get("url", ""),
                    "notes": row.get("notes", ""),
                    "tags": [tag.strip() for tag in row.get("tags", "").split("|") if tag.strip()],
                    "entry_type": row.get("entry_type", "login"),
                    "custom_fields": json.loads(row["custom_fields"]) if row.get("custom_fields") else [],
                    "totp_secret": row.get("totp_secret", ""),
                    "attachments": [],
                }
            )
    else:
        raise ValueError("format must be json or csv")
    if len(values) > MAX_TRANSFER_ENTRIES:
        raise ValueError("transfer contains too many entries")
    try:
        return [_entry_from_json(item) for item in values]
    except (TypeError, PersonalDataError) as exc:
        raise ValueError(str(exc)) from exc


def import_entries(vault: Any, entries: list[ImportedEntry]) -> dict[str, int]:
    # Validate and prepare the entire transfer before changing the encrypted
    # vault.  Once prepared, LocalVault performs a single atomic save.
    prepared: list[SecretEntry] = []
    for item in entries:
        entry = SecretEntry(
            title=item.title,
            username=item.username,
            password=item.password,
            url=item.url,
            notes=item.notes,
            tags=item.tags,
        )
        update_data(
            entry,
            entry_type=item.entry_type,
            custom_fields=item.custom_fields,
            totp_secret=item.totp_secret,
        )
        personal = data_for(entry)
        # Attachment integrity and size limits are validated through the same
        # personal-data schema before the entry is saved.
        personal["attachments"] = item.attachments
        set_data(entry, personal)
        prepared.append(entry)
    vault.local.import_entries(prepared, from_remote=False)
    return {"imported": len(entries)}


def export_transfer(vault: Any, format_name: str) -> tuple[str, str, str]:
    values: list[dict[str, Any]] = []
    for entry in vault.local.list_entries():
        personal = data_for(entry)
        values.append(
            {
                "title": entry.title,
                "username": entry.username,
                "password": entry.password,
                "url": entry.url,
                "notes": entry.notes,
                "tags": list(entry.tags),
                "entry_type": personal["entry_type"],
                "custom_fields": personal["custom_fields"],
                "totp_secret": personal["totp_secret"],
                "attachments": personal["attachments"],
            }
        )
    if format_name == "json":
        return (
            json.dumps({"schema": JSON_SCHEMA, "version": JSON_VERSION, "entries": values}, ensure_ascii=False, indent=2),
            "vault-unified-export.json",
            "application/json",
        )
    if format_name == "csv":
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "title",
                "username",
                "password",
                "url",
                "notes",
                "tags",
                "entry_type",
                "custom_fields",
                "totp_secret",
            ],
        )
        writer.writeheader()
        for value in values:
            writer.writerow(
                {
                    **value,
                    "tags": "|".join(value["tags"]),
                    "custom_fields": json.dumps(value["custom_fields"], ensure_ascii=False),
                }
            )
        return stream.getvalue(), "vault-unified-export.csv", "text/csv"
    raise ValueError("format must be json or csv")

"""Explicit two-entry merges with recoverable source and retained histories."""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from urllib.parse import urlsplit
from uuid import uuid4

from vault_unified.models import SecretEntry
from vault_unified.organization import is_fillable, prepare_action
from vault_unified.personal_data import (
    MAX_MERGED_HISTORY_ITEMS, MERGED_HISTORY_KEY, all_history,
    data_for, set_data, snapshot,
)

MERGE_FIELDS = frozenset({"title", "username", "password", "url", "notes", "tags", "custom_fields", "totp_secret"})


def duplicate_key(entry: SecretEntry) -> tuple[str, str] | None:
    if not is_fillable(entry) or data_for(entry)["entry_type"] != "login":
        return None
    if not entry.username:
        return None
    if entry.url:
        try:
            url = urlsplit(entry.url)
            if url.scheme not in {"https", "http"} or not url.hostname or url.username or url.password:
                return None
            host = url.hostname.rstrip(".").encode("idna").decode("ascii").lower()
            site = f"host:{host}:{url.port or (443 if url.scheme == 'https' else 80)}"
        except (ValueError, UnicodeError):
            return None
    else:
        site = "title:" + entry.title.strip().casefold()
    return site, entry.username


def duplicate_groups(entries: list[SecretEntry]) -> list[list[str]]:
    groups: dict[tuple[str, str], list[str]] = {}
    for entry in entries:
        key = duplicate_key(entry)
        if key:
            groups.setdefault(key, []).append(entry.id)
    return [ids for ids in groups.values() if len(ids) > 1]


def prepare_merge(target: SecretEntry, source: SecretEntry, choices: dict[str, str]) -> list[SecretEntry]:
    if target.id == source.id or not duplicate_key(target) or duplicate_key(target) != duplicate_key(source):
        raise ValueError("Select two active logins with the same website and username")
    if set(choices) != MERGE_FIELDS or any(value not in {"target", "source"} for value in choices.values()):
        raise ValueError("Choose a value for every merge field")
    candidate = copy.deepcopy(target)
    personal = data_for(candidate)
    other = data_for(source)
    for field, side in choices.items():
        if side == "source":
            if field in {"custom_fields", "totp_secret"}:
                personal[field] = copy.deepcopy(other[field])
            else:
                setattr(candidate, field, copy.deepcopy(getattr(source, field)))

    attachments = personal["attachments"]
    attachment_ids: dict[str, str] = {}
    for original in other["attachments"]:
        same = next((item for item in attachments if (item["filename"], item["mime_type"], item["sha256"]) == (original["filename"], original["mime_type"], original["sha256"])), None)
        if same:
            attachment_ids[original["id"]] = same["id"]
            continue
        attachment = copy.deepcopy(original)
        if any(item["id"] == attachment["id"] for item in attachments):
            attachment["id"] = str(uuid4())
        attachment_ids[original["id"]] = attachment["id"]
        attachments.append(attachment)
    # Existing attachment limits fail before any write; no binary is silently lost.
    set_data(candidate, personal)

    # Retain both current versions and every existing history, including versions
    # from earlier merges. This archive is not truncated by ordinary later edits.
    histories: dict[str, dict] = {}
    for entry in (target, source):
        current = {"id": str(uuid4()), "saved_at": datetime.now(timezone.utc).isoformat(), "snapshot": snapshot(entry)}
        for item in [*all_history(entry), current]:
            item = copy.deepcopy(item)
            if entry is source:
                item["snapshot"]["attachment_ids"] = [attachment_ids.get(value, value) for value in item["snapshot"].get("attachment_ids", [])]
            if item["id"] in histories and histories[item["id"]] != item:
                item = {**item, "id": str(uuid4())}
            histories[item["id"]] = item
    if len(histories) > MAX_MERGED_HISTORY_ITEMS:
        raise ValueError("Combined history exceeds the merge limit; both accounts remain unchanged")
    candidate.source_metadata[MERGED_HISTORY_KEY] = {"version": 1, "items": list(histories.values())}

    candidate.mark_dirty()
    return [candidate, prepare_action(source, "trash", tags=[])]

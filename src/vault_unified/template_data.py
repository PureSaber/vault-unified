"""Encrypted structured data for practical personal credential templates."""
from __future__ import annotations

import copy
from datetime import date, datetime
from typing import Any

TEMPLATE_KEY = "vault_unified:template"
NEW_ENTRY_TYPES = frozenset({"software_license", "api_credential"})
TEXT_FIELDS = {"registered_to": 500, "environment": 128, "scopes": 4096, "expires_on": 10}


def normalize_template(value: Any) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict) or set(value) - {*TEXT_FIELDS, "recovery_codes"}:
        raise ValueError("Template fields have an invalid shape")
    result = {}
    for key, limit in TEXT_FIELDS.items():
        text = value.get(key, "")
        if not isinstance(text, str) or len(text) > limit:
            raise ValueError("Template text exceeds its field limit")
        if text:
            if key == "expires_on":
                try:
                    if date.fromisoformat(text).isoformat() != text:
                        raise ValueError()
                except ValueError as exc:
                    raise ValueError("Expiry must be a YYYY-MM-DD date") from exc
            result[key] = text
    codes = value.get("recovery_codes", [])
    if not isinstance(codes, list) or len(codes) > 100:
        raise ValueError("An entry can contain at most 100 recovery codes")
    ids, values = set(), set()
    for code in codes:
        if not isinstance(code, dict) or set(code) != {"id", "value", "used_at"}:
            raise ValueError("Recovery code has an invalid shape")
        if any(not isinstance(code[field], str) for field in code):
            raise ValueError("Recovery code fields must be text")
        if not code["id"] or len(code["id"]) > 64 or code["id"] in ids:
            raise ValueError("Recovery codes need unique identifiers")
        if not code["value"].strip() or len(code["value"]) > 1024 or code["value"] in values:
            raise ValueError("Recovery codes must be nonempty, distinct and at most 1024 characters")
        if code["used_at"]:
            try:
                if len(code["used_at"]) > 64 or datetime.fromisoformat(code["used_at"].replace("Z", "+00:00")).tzinfo is None:
                    raise ValueError()
            except ValueError as exc:
                raise ValueError("Used-code time must include a time zone") from exc
        ids.add(code["id"]); values.add(code["value"])
    if codes:
        result["recovery_codes"] = copy.deepcopy(codes)
    return result


def template_for(entry: Any) -> dict:
    stored = entry.source_metadata.get(TEMPLATE_KEY)
    if stored is None:
        return {}
    if not isinstance(stored, dict) or set(stored) != {"version", "data"} or type(stored["version"]) is not int or stored["version"] != 1:
        raise ValueError("Template data has an unsupported schema")
    return normalize_template(stored["data"])


def set_template(entry: Any, value: dict) -> None:
    data = normalize_template(value)
    if data:
        entry.source_metadata[TEMPLATE_KEY] = {"version": 1, "data": data}
    else:
        entry.source_metadata.pop(TEMPLATE_KEY, None)


def require_template_payload(vault: Any, entries: list[Any]) -> None:
    if vault.payload_version >= 3:
        return
    for entry in entries:
        kind = entry.source_metadata.get("vault_unified:personal", {}).get("entry_type", "login")
        if kind in NEW_ENTRY_TYPES or TEMPLATE_KEY in entry.source_metadata:
            raise ValueError("Upgrade the vault in Security & recovery before saving credential templates")

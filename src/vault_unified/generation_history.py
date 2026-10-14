"""Generated secrets retained inside the existing encrypted vault payload."""
from __future__ import annotations

import time
from urllib.parse import urlsplit
from uuid import uuid4

from vault_unified.generator import generate_password, generate_passphrase
from vault_unified.local_store import LocalVault

NAMESPACE = "vault_unified:generated_passwords"
MAX_RECORDS = 100
MAX_AGE_SECONDS = 30 * 86400


def retained(value: dict | None, *, now: float | None = None) -> dict:
    if value is None:
        return {"version": 1, "items": []}
    if not isinstance(value, dict) or value.get("version") != 1 or not isinstance(value.get("items"), list):
        raise ValueError("Unsupported generated-password history format")
    stamp = time.time() if now is None else now
    records = value["items"]
    if any(not isinstance(item, dict) or not isinstance(item.get("created_at"), (int, float)) for item in records):
        raise ValueError("Invalid generated-password history")
    # Keep future-dated records after a clock correction; count remains bounded.
    return {**value, "items": sorted((item for item in records if item["created_at"] > stamp - MAX_AGE_SECONDS), key=lambda item: (item["created_at"], item["id"]), reverse=True)[:MAX_RECORDS]}


def prune(local: LocalVault) -> None:
    if local.payload_version == 3 and local.metadata_value(NAMESPACE) is not None:
        local.update_metadata(NAMESPACE, retained)


def origin_hint(value: str) -> str:
    try:
        url = urlsplit(value)
        if url.scheme not in {"https", "http"} or not url.hostname or url.username is not None or url.password is not None:
            return ""
        host = url.hostname.encode("idna").decode("ascii").lower()
        if ":" in host:
            host = f"[{host}]"
        port = url.port
        return f"{url.scheme}://{host}" + (f":{port}" if port and port != (443 if url.scheme == "https" else 80) else "")
    except (ValueError, UnicodeError):
        return ""


def generate_saved(local: LocalVault, *, kind: str = "password", length: int = 20,
                   symbols: bool = True, digits: bool = True, upper: bool = True, lower: bool = True,
                   allowed: str = "", excluded: str = "", words: int = 6,
                   separator: str = "-", url: str = "", request_id: str | None = None) -> dict:
    if kind not in {"password", "passphrase"}:
        raise ValueError("Unknown generator type")
    record_id = request_id or str(uuid4())
    def generate() -> str:
        return generate_passphrase(words, separator=separator) if kind == "passphrase" else generate_password(length, symbols=symbols, digits=digits, upper=upper, lower=lower, allowed=allowed, excluded=excluded)
    if local.payload_version < 3:
        return {"password": generate(), "history_saved": False}
    def append(value):
        state = retained(value)
        if any(item["id"] == record_id for item in state["items"]):
            return state
        record = {"id": record_id, "value": generate(), "kind": kind, "created_at": time.time(), "origin": origin_hint(url)}
        return {**state, "items": [record, *state["items"]][:MAX_RECORDS]}
    saved = local.update_metadata(NAMESPACE, append)
    record = next(item for item in saved["items"] if item["id"] == record_id)
    return {"password": record["value"], "history_saved": True, "history_id": record_id}


def list_generated(local: LocalVault) -> list[dict]:
    return [{key: item[key] for key in ("id", "kind", "created_at", "origin")} for item in retained(local.metadata_value(NAMESPACE))["items"]]


def get_generated(local: LocalVault, record_id: str) -> dict:
    for item in retained(local.metadata_value(NAMESPACE))["items"]:
        if item["id"] == record_id:
            return item
    raise KeyError("Generated password expired or was not found")

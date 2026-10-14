"""Authenticated immutable change records with names bound to the sync space."""
from __future__ import annotations

import json
import math
import re
import secrets
from uuid import UUID

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAX_RECORD_BYTES = 32 * 1024 * 1024
MAX_SEQUENCE = 999_999_999_999
STATE_NAMESPACE = "vault_unified:personal_sync"
_IDENTIFIER = re.compile(r"[a-f0-9]{32}\Z")
_NAME = re.compile(r"([a-f0-9]{32})-([0-9]{12})\.vuc\Z")


class ProtocolError(ValueError):
    pass


def identifier(value):
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ProtocolError("Invalid synchronization identity")
    return value


def filename(device: str, sequence: int) -> str:
    identifier(device)
    if type(sequence) is not int or not 1 <= sequence <= MAX_SEQUENCE:
        raise ProtocolError("Invalid change sequence")
    return f"{device}-{sequence:012d}.vuc"


def record_identity(name: str) -> tuple[str, int]:
    match = _NAME.fullmatch(name)
    if not match or int(match[2]) == 0:
        raise ProtocolError("Invalid change filename")
    return match[1], int(match[2])


def _finite_json(value, depth=0):
    if depth > 40:
        raise ProtocolError("Change data is nested too deeply")
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float and math.isfinite(value):
        return
    if isinstance(value, list):
        for item in value:
            _finite_json(item, depth + 1)
        return
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        for item in value.values():
            _finite_json(item, depth + 1)
        return
    raise ProtocolError("Change data is not finite JSON")


def validate_record(record: dict, space: str, name: str) -> dict:
    device, sequence = record_identity(name)
    identifier(space)
    if not isinstance(record, dict) or set(record) != {"version", "space", "device", "sequence", "context", "object", "before", "after", "resolution"}:
        raise ProtocolError("Unsupported change record")
    if type(record["version"]) is not int or record["version"] != 1 or record["space"] != space or record["device"] != device or type(record["sequence"]) is not int or record["sequence"] != sequence:
        raise ProtocolError("Change identity mismatch")
    context = record["context"]
    if not isinstance(context, dict) or len(context) > 256:
        raise ProtocolError("Invalid change context")
    for member, counter in context.items():
        identifier(member)
        if type(counter) is not int or not 0 <= counter <= MAX_SEQUENCE:
            raise ProtocolError("Invalid change context")
    if context.get(device, 0) != sequence - 1:
        raise ProtocolError("Change sequence has a gap")
    if not isinstance(record["object"], str) or not 1 <= len(record["object"]) <= 512 or not record["object"].startswith(("entry/", "metadata/", "device/")):
        raise ProtocolError("Invalid synchronized object")
    if type(record["resolution"]) is not bool or any(value is not None and not isinstance(value, dict) for value in (record["before"], record["after"])) or (record["before"] == record["after"] and not record["resolution"]):
        raise ProtocolError("Invalid change values")
    kind, object_id = record["object"].split("/", 1)
    if not object_id or any(ord(char) < 32 for char in object_id):
        raise ProtocolError("Invalid synchronized object")
    if kind == "entry":
        try:
            if str(UUID(object_id)) != object_id:
                raise ValueError()
        except ValueError:
            raise ProtocolError("Invalid entry identity") from None
        if any(value is not None and value.get("id") != object_id for value in (record["before"], record["after"])):
            raise ProtocolError("Entry identity mismatch")
    if kind == "device" and object_id != device:
        raise ProtocolError("A device cannot announce another device")
    if kind == "metadata" and object_id == STATE_NAMESPACE:
        raise ProtocolError("Local replication state cannot be synchronized")
    _finite_json(record)
    return record


def seal(key: bytes, space: str, record: dict) -> tuple[str, bytes]:
    name = filename(record["device"], record["sequence"])
    validate_record(record, space, name)
    plain = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(key) != 32 or len(plain) + 32 > MAX_RECORD_BYTES:
        raise ProtocolError("Change record exceeds its limit")
    nonce = secrets.token_bytes(12)
    aad = f"VaultUnifiedSync/1/{space}/{name}".encode("ascii")
    return name, b"VUS1" + nonce + AESGCM(key).encrypt(nonce, plain, aad)


def unseal(key: bytes, space: str, name: str, encrypted: bytes) -> dict:
    try:
        identifier(space); record_identity(name)
        if len(key) != 32 or not 32 <= len(encrypted) <= MAX_RECORD_BYTES or encrypted[:4] != b"VUS1":
            raise ValueError()
        plain = AESGCM(key).decrypt(encrypted[4:16], encrypted[16:], f"VaultUnifiedSync/1/{space}/{name}".encode("ascii"))
        record = json.loads(plain)
        return validate_record(record, space, name)
    except Exception:
        raise ProtocolError("Synchronized change could not be authenticated or parsed") from None

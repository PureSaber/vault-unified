"""Versioned envelopes shared by the desktop client and the ciphertext service."""
from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import time
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

VERSION = 1
MAX_BLOB = 12 * 1024 * 1024
MAX_BODY = 18 * 1024 * 1024


class SharingError(ValueError):
    """Sanitized failure without remote response bodies or secret values."""


def encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def decode(value, size=None, maximum=MAX_BLOB):
    if not isinstance(value, str) or len(value) > (maximum * 4 + 2) // 3 or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise SharingError("Invalid sharing envelope")
    try: result = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except ValueError: raise SharingError("Invalid sharing envelope") from None
    if encode(result) != value or len(result) > maximum or (size is not None and len(result) != size):
        raise SharingError("Invalid sharing envelope")
    return result


def canonical(value) -> bytes:
    try: result = json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode()
    except (TypeError, ValueError, RecursionError): raise SharingError("Invalid sharing document") from None
    if len(result) > MAX_BODY: raise SharingError("Sharing document is too large")
    return result


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{32}", value):
        raise SharingError("Invalid sharing identifier")
    return value


def service_url(value):
    try:
        parts = urlsplit(value)
        if (parts.username or parts.password or parts.query or parts.fragment or parts.path not in {"", "/"}
                or not parts.hostname or parts.scheme not in {"http", "https"}
                or (parts.scheme == "http" and parts.hostname not in {"127.0.0.1", "localhost", "::1"})):
            raise ValueError()
        _ = parts.port
        return value.rstrip("/")
    except (ValueError, TypeError): raise SharingError("Use an HTTPS sharing service address, or HTTP on localhost") from None


def raw_private(key):
    return key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())


def raw_public(key):
    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def new_identity():
    return {"version": VERSION, "signing_private": encode(raw_private(Ed25519PrivateKey.generate())),
            "encryption_private": encode(raw_private(X25519PrivateKey.generate()))}


def public_identity(identity):
    signing = Ed25519PrivateKey.from_private_bytes(decode(identity["signing_private"], 32))
    encryption = X25519PrivateKey.from_private_bytes(decode(identity["encryption_private"], 32))
    return {"signing_key": encode(raw_public(signing)), "encryption_key": encode(raw_public(encryption))}


def member_id(public_key):
    return hashlib.sha256(decode(public_key, 32)).hexdigest()


def sign(identity, value):
    return encode(Ed25519PrivateKey.from_private_bytes(decode(identity["signing_private"], 32)).sign(canonical(value)))


def verify(public_key, value, signature):
    try: Ed25519PublicKey.from_public_bytes(decode(public_key, 32)).verify(decode(signature, 64), canonical(value))
    except (InvalidSignature, ValueError): raise SharingError("Sharing signature did not verify") from None


def signed_request(identity, path, payload, *, now=None):
    value = {"version": VERSION, "path": path, "timestamp": int(time.time() if now is None else now),
             "nonce": secrets.token_hex(16), "identity": public_identity(identity)["signing_key"], "payload": payload}
    return {**value, "signature": sign(identity, value)}


def verify_request(value, path, now):
    if not isinstance(value, dict) or set(value) != {"version", "path", "timestamp", "nonce", "identity", "payload", "signature"}:
        raise SharingError("Invalid signed sharing request")
    if value["version"] != VERSION or value["path"] != path or type(value["timestamp"]) is not int or abs(now - value["timestamp"]) > 60:
        raise SharingError("Sharing request expired or changed")
    identifier(value["nonce"])
    if not isinstance(value["payload"], dict): raise SharingError("Invalid sharing request")
    verify(value["identity"], {k: v for k, v in value.items() if k != "signature"}, value["signature"])
    return member_id(value["identity"])


def encrypt(key: bytes, value, context: str):
    plain = canonical(value)
    if len(plain) > MAX_BLOB - 28: raise SharingError("Shared content is too large")
    nonce = secrets.token_bytes(12)
    return encode(nonce + AESGCM(key).encrypt(nonce, plain, context.encode()))


def decrypt(key: bytes, value, context: str):
    blob = decode(value)
    try: return json.loads(AESGCM(key).decrypt(blob[:12], blob[12:], context.encode()))
    except (InvalidTag, ValueError, UnicodeError, RecursionError): raise SharingError("Shared content did not verify") from None


def validate_blob(value):
    if len(decode(value)) < 28: raise SharingError("Invalid encrypted content")
    return value


def wrap_key(public_key, key: bytes, context: str):
    ephemeral = X25519PrivateKey.generate()
    try: shared = ephemeral.exchange(X25519PublicKey.from_public_bytes(decode(public_key, 32)))
    except ValueError: raise SharingError("Invalid member encryption key") from None
    wrapping = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=("vault-unified:family-wrap:v1:" + context).encode()).derive(shared)
    return {"ephemeral": encode(raw_public(ephemeral)), "ciphertext": encrypt(wrapping, {"key": encode(key)}, context)}


def unwrap_key(identity, envelope, context):
    try:
        key = X25519PrivateKey.from_private_bytes(decode(identity["encryption_private"], 32))
        shared = key.exchange(X25519PublicKey.from_public_bytes(decode(envelope["ephemeral"], 32)))
        wrapping = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=("vault-unified:family-wrap:v1:" + context).encode()).derive(shared)
        return decode(decrypt(wrapping, envelope["ciphertext"], context)["key"], 32)
    except (KeyError, TypeError, ValueError): raise SharingError("Shared vault key did not verify") from None


def validate_manifest(manifest, owner, signature, group):
    if not isinstance(manifest, dict) or set(manifest) != {"version", "group", "epoch", "members"} or manifest["version"] != VERSION or manifest["group"] != group:
        raise SharingError("Invalid family membership")
    if type(manifest["epoch"]) is not int or not 1 <= manifest["epoch"] <= 2**31: raise SharingError("Invalid family epoch")
    members = manifest["members"]
    if not isinstance(members, dict) or not 1 <= len(members) <= 32: raise SharingError("A family supports up to 32 members")
    owners = []
    for mid, member in members.items():
        if not isinstance(member, dict) or set(member) != {"signing_key", "encryption_key", "role", "wrapped_key"} or mid != member_id(member["signing_key"]):
            raise SharingError("Invalid family identity")
        decode(member["encryption_key"], 32)
        if member["role"] not in {"owner", "editor", "reader"}: raise SharingError("Invalid family role")
        if member["role"] == "owner": owners.append(member["signing_key"])
        envelope = member["wrapped_key"]
        if not isinstance(envelope, dict) or set(envelope) != {"ephemeral", "ciphertext"}: raise SharingError("Invalid family key envelope")
        decode(envelope["ephemeral"], 32)
        if len(decode(envelope["ciphertext"], maximum=1024)) < 28: raise SharingError("Invalid family key envelope")
    if owners != [owner]: raise SharingError("The original family owner must be retained")
    verify(owner, manifest, signature)
    return manifest

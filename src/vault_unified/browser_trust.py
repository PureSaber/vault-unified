"""Revocable browser public keys protected by the Windows credential store.

No bearer token or vault decryption key is persisted here. A browser must prove
possession of its private key for every new desktop session. Device records and
their bounded index fit in individual Windows credential records; deleting the
device record first makes revocation fail closed even if updating the index fails.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import threading
import time
from datetime import datetime, timezone
from typing import Any

from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from vault_unified.config import get_config_dir
from vault_unified.device_keyring import get_approved_backend

SERVICE = "vault-unified:browser-trust:v1"
MAX_DEVICES = 16
MAX_CHALLENGES = 128
CHALLENGE_SECONDS = 60
_ID = re.compile(r"^[a-f0-9]{32}$")
_ORIGIN = re.compile(r"^chrome-extension://[a-p]{32}$")


class BrowserTrustError(ValueError):
    pass


class BrowserTrustUnavailable(BrowserTrustError):
    pass


def _public_key(encoded: str) -> ec.EllipticCurvePublicKey:
    try:
        raw = base64.b64decode(encoded, validate=True)
        key = serialization.load_der_public_key(raw)
        if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(key.curve, ec.SECP256R1):
            raise ValueError()
        return key
    except (TypeError, ValueError, UnsupportedAlgorithm) as exc:
        raise BrowserTrustError("Invalid browser identity") from exc


class BrowserTrustStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._challenges: dict[str, tuple[float, str, str, str, str]] = {}

    @staticmethod
    def _account(suffix: str) -> str:
        # Scope development/portable installations independently. This identifier
        # is not an authorization credential and contains no vault contents.
        scope = hashlib.sha256(str(get_config_dir().resolve()).encode()).hexdigest()
        return f"{scope}:{suffix}"

    def _read(self, suffix: str) -> Any:
        try:
            raw = get_approved_backend().get_password(SERVICE, self._account(suffix))
            if raw is None:
                return None
            return json.loads(raw)
        except Exception as exc:
            raise BrowserTrustUnavailable("Browser device storage is unavailable") from exc

    def _write(self, suffix: str, value: Any) -> None:
        raw = json.dumps(value, ensure_ascii=True, separators=(",", ":"))
        # WinVaultKeyring writes a UTF-16 credential blob (2560-byte limit).
        if len(raw.encode("utf-16-le")) > 2500:
            raise BrowserTrustError("Browser device details exceed the supported size")
        try:
            get_approved_backend().set_password(SERVICE, self._account(suffix), raw)
        except Exception as exc:
            raise BrowserTrustUnavailable("Browser device storage is unavailable") from exc

    def _delete(self, suffix: str) -> None:
        try:
            get_approved_backend().delete_password(SERVICE, self._account(suffix))
        except Exception as exc:
            raise BrowserTrustUnavailable("Browser device could not be revoked") from exc

    def _index(self) -> list[str]:
        value = self._read("index")
        if value is None:
            return []
        if (not isinstance(value, list) or len(value) > MAX_DEVICES
                or any(not isinstance(item, str) or not _ID.fullmatch(item) for item in value)
                or len(set(value)) != len(value)):
            raise BrowserTrustUnavailable("Browser device storage is invalid")
        return value

    def _record(self, device_id: str) -> dict | None:
        if not _ID.fullmatch(device_id):
            raise BrowserTrustError("Browser device is not authorized")
        record = self._read(device_id)
        if record is None:
            return None
        if (not isinstance(record, dict) or set(record) != {"id", "binding", "origin", "public_key", "name", "created_at"}
                or record.get("id") != device_id
                or not isinstance(record.get("binding"), list) or len(record["binding"]) != 3
                or any(not isinstance(item, str) or not item for item in record["binding"])
                or not isinstance(record.get("origin"), str) or not _ORIGIN.fullmatch(record["origin"])
                or not all(isinstance(record.get(key), str) for key in ("public_key", "name", "created_at"))):
            raise BrowserTrustUnavailable("Browser device storage is invalid")
        try:
            _public_key(record["public_key"])
        except BrowserTrustError as exc:
            raise BrowserTrustUnavailable("Browser device storage is invalid") from exc
        return record

    def enroll(self, binding: tuple[str, str, str], origin: str, public_key: str, name: str) -> dict:
        if not _ORIGIN.fullmatch(origin):
            raise BrowserTrustError("Invalid browser identity")
        _public_key(public_key)
        if not name.strip() or len(name) > 64 or any(ord(c) < 32 for c in name):
            raise BrowserTrustError("Invalid browser device name")
        with self._lock:
            ids = self._index()
            # Missing credentials are already revoked; repair only the index.
            ids = [item for item in ids if self._record(item) is not None]
            if len(ids) >= MAX_DEVICES:
                raise BrowserTrustError("Revoke an existing browser before adding another")
            device_id = secrets.token_hex(16)
            record = {"id": device_id, "binding": list(binding), "origin": origin,
                      "public_key": public_key, "name": name.strip(),
                      "created_at": datetime.now(timezone.utc).isoformat()}
            self._write(device_id, record)
            try:
                self._write("index", [*ids, device_id])
            except Exception:
                self._delete(device_id)
                raise
            return record

    def load(self, device_id: str, origin: str) -> dict:
        if not _ORIGIN.fullmatch(origin) or not _ID.fullmatch(device_id):
            raise BrowserTrustError("Browser device is not authorized")
        with self._lock:
            if device_id not in self._index():
                raise BrowserTrustError("Browser device is not authorized")
            record = self._record(device_id)
            if record is None or not secrets.compare_digest(record["origin"], origin):
                raise BrowserTrustError("Browser device is not authorized")
            return record

    def list_for(self, binding: tuple[str, str, str] | None) -> list[dict]:
        with self._lock:
            records = [self._record(item) for item in self._index()]
            return [{key: item[key] for key in ("id", "name", "origin", "created_at")}
                    for item in records if item and tuple(item["binding"]) == binding]

    def revoke(self, binding: tuple[str, str, str], device_id: str) -> None:
        with self._lock:
            ids = self._index()
            if device_id not in ids:
                return
            record = self._record(device_id)
            if record and tuple(record["binding"]) != binding:
                raise BrowserTrustError("Browser device belongs to another vault")
            if record:
                self._delete(device_id)
            self._write("index", [item for item in ids if item != device_id])

    def challenge(self, device_id: str, origin: str, action: str) -> dict:
        if action not in {"resume", "revoke"}:
            raise BrowserTrustError("Invalid browser authorization action")
        with self._lock:
            self.load(device_id, origin)
            now = time.monotonic()
            self._challenges = {k: v for k, v in self._challenges.items() if v[0] > now}
            if len(self._challenges) >= MAX_CHALLENGES:
                raise BrowserTrustError("Too many browser authorization requests; retry shortly")
            challenge_id = secrets.token_urlsafe(32)
            message = f"VaultUnified browser authorization v1\n{action}\n{device_id}\n{origin}\n{challenge_id}"
            self._challenges[challenge_id] = (now + CHALLENGE_SECONDS, device_id, origin, action, message)
            return {"challenge_id": challenge_id, "message": message, "expires_in_seconds": CHALLENGE_SECONDS}

    def verify(self, device_id: str, origin: str, action: str, challenge_id: str, signature: str) -> dict:
        with self._lock:
            pending = self._challenges.pop(challenge_id, None)
            if pending is None or pending[0] <= time.monotonic() or pending[1:4] != (device_id, origin, action):
                raise BrowserTrustError("Browser authorization expired or is invalid")
            record = self.load(device_id, origin)  # Recheck revocation after the challenge.
            try:
                raw = base64.b64decode(signature, validate=True)
                if len(raw) != 64:
                    raise ValueError()
                der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
                _public_key(record["public_key"]).verify(der, pending[4].encode(), ec.ECDSA(hashes.SHA256()))
            except (InvalidSignature, TypeError, ValueError) as exc:
                raise BrowserTrustError("Browser authorization is invalid") from exc
            return record

    def clear_challenges(self) -> None:
        with self._lock:
            self._challenges.clear()


browser_trust = BrowserTrustStore()

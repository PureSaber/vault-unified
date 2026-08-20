from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import struct
import threading
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from cryptography.exceptions import InvalidTag, UnsupportedAlgorithm
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id

from vault_unified.storage import atomic_write_bytes, require_clean_storage
from vault_unified.vault_format import (
    MAX_VAULT_BYTES,
    V3_MAGIC,
    WINDOWS_DEVICE_KEYRING_BACKEND,
    Argon2idParameters,
    DeviceSlotHeader,
    KeySlotHeader,
    PasswordSlotHeader,
    V3Container,
    V3Header,
    VaultFormatError,
    parse_vault_container,
)


DEFAULT_MEMORY_KIB = 65_536
DEFAULT_PASSES = 3
DEFAULT_LANES = 4
ARGON2_VERSION = 19
KEY_BYTES = 32
SALT_BYTES = 16
NONCE_BYTES = 12
MAX_PASSWORD_BYTES = 1024
MAX_JSON_DEPTH = 32
MAX_ENTRY_COUNT = 100_000

WRAP_AAD_DOMAIN = b"vault-unified:v3:wrap"
PAYLOAD_AAD_DOMAIN = b"vault-unified:v3:payload"
ROLLBACK_ANCHOR_EXTENSION = "vault-unified:rollback-anchor"
_ARGON2_LOCK = threading.Lock()


class V3CryptoError(ValueError):
    """Base error for v3 authenticated encryption operations."""


class V3CryptoUnavailableError(V3CryptoError):
    """The installed cryptographic backend cannot provide Argon2id."""


class V3AuthenticationError(V3CryptoError):
    """Password unwrap or authenticated payload decryption failed."""


class V3PayloadError(V3CryptoError):
    """Authenticated plaintext violates payload schema or resource limits."""


class V3PasswordSlotSelectionRequired(V3CryptoError):
    """More than one password slot exists and no reviewed selector is available."""


@dataclass(frozen=True)
class V3DeviceCredential:
    """In-memory device KEK reference. The key is never serialized into a vault file."""

    slot_id: str
    key: bytes

    def __post_init__(self) -> None:
        try:
            canonical = str(UUID(self.slot_id))
        except (ValueError, AttributeError) as exc:
            raise V3CryptoError("Device slot ID is not a UUID") from exc
        if canonical != self.slot_id:
            raise V3CryptoError("Device slot ID is not canonical")
        if not isinstance(self.key, bytes) or len(self.key) != KEY_BYTES:
            raise V3CryptoError("Device key must be exactly 32 bytes")


V3Credential = str | V3DeviceCredential


@dataclass(frozen=True)
class V3CreationMaterials:
    """Deterministic materials accepted only by underscore-prefixed test helpers."""

    vault_id: str
    dek_id: str
    slot_id: str
    salt: bytes
    wrap_nonce: bytes
    payload_nonce: bytes
    dek: bytes


def _random_materials(*, vault_id: str | None = None) -> V3CreationMaterials:
    return V3CreationMaterials(
        vault_id=vault_id or str(uuid4()),
        dek_id=str(uuid4()),
        slot_id=str(uuid4()),
        salt=os.urandom(SALT_BYTES),
        wrap_nonce=os.urandom(NONCE_BYTES),
        payload_nonce=os.urandom(NONCE_BYTES),
        dek=AESGCM.generate_key(bit_length=256),
    )


def _validate_materials(materials: V3CreationMaterials) -> None:
    for name, value in (
        ("vault_id", materials.vault_id),
        ("dek_id", materials.dek_id),
        ("slot_id", materials.slot_id),
    ):
        try:
            parsed = str(UUID(value))
        except (ValueError, AttributeError) as exc:
            raise V3CryptoError(f"{name} is not a UUID") from exc
        if parsed != value:
            raise V3CryptoError(f"{name} is not canonical")
    for name, value, length in (
        ("salt", materials.salt, SALT_BYTES),
        ("wrap_nonce", materials.wrap_nonce, NONCE_BYTES),
        ("payload_nonce", materials.payload_nonce, NONCE_BYTES),
        ("dek", materials.dek, KEY_BYTES),
    ):
        if not isinstance(value, bytes) or len(value) != length:
            raise V3CryptoError(f"{name} must be exactly {length} bytes")


def _password_bytes(password: str) -> bytes:
    if not isinstance(password, str):
        raise TypeError("V3 password must be a string")
    try:
        encoded = password.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise V3CryptoError("V3 password must be valid Unicode") from exc
    if not encoded or len(encoded) > MAX_PASSWORD_BYTES:
        raise V3CryptoError("V3 password must contain 1-1024 UTF-8 bytes")
    return encoded


def _derive_kek(password: str, params: Argon2idParameters) -> bytes:
    material = _password_bytes(password)
    try:
        with _ARGON2_LOCK:
            return Argon2id(
                salt=params.salt,
                length=params.output_bytes,
                iterations=params.passes,
                lanes=params.lanes,
                memory_cost=params.memory_kib,
                ad=None,
                secret=None,
            ).derive(material)
    except UnsupportedAlgorithm as exc:
        raise V3CryptoUnavailableError(
            "Argon2id requires cryptography >=44 with a supported OpenSSL backend"
        ) from exc
    except MemoryError as exc:
        raise V3CryptoUnavailableError("Insufficient memory for stored Argon2id policy") from exc


def _length_prefix(value: bytes) -> bytes:
    return struct.pack(">I", len(value)) + value


def _integer(value: int) -> bytes:
    return struct.pack(">Q", value)


def _typed_aad(domain: bytes, fields: tuple[tuple[str, bytes], ...]) -> bytes:
    encoded = [_length_prefix(domain)]
    for name, value in fields:
        encoded.append(_length_prefix(name.encode("ascii")))
        encoded.append(_length_prefix(value))
    return b"".join(encoded)


def _wrap_aad(header: V3Header, slot: KeySlotHeader) -> bytes:
    common = (
            ("format_version", _integer(header.format_version)),
            ("cipher", header.cipher.encode("ascii")),
            ("vault_id", UUID(header.vault_id).bytes),
            ("dek_id", UUID(header.dek_id).bytes),
            ("key_generation", _integer(header.key_generation)),
            ("slot_id", UUID(slot.slot_id).bytes),
    )
    if isinstance(slot, PasswordSlotHeader):
        fields = common + (
            ("slot_type", b"password"),
            ("kdf", b"argon2id"),
            ("argon2_version", _integer(slot.kdf.version)),
            ("memory_kib", _integer(slot.kdf.memory_kib)),
            ("passes", _integer(slot.kdf.passes)),
            ("lanes", _integer(slot.kdf.lanes)),
            ("salt", slot.kdf.salt),
            ("output_bytes", _integer(slot.kdf.output_bytes)),
            ("wrap_cipher", slot.wrap_cipher.encode("ascii")),
            ("wrap_nonce", slot.wrap_nonce),
        )
    else:
        fields = common + (
            ("slot_type", b"device"),
            ("keyring_backend", slot.keyring_backend.encode("ascii")),
            ("wrap_cipher", slot.wrap_cipher.encode("ascii")),
            ("wrap_nonce", slot.wrap_nonce),
        )
    return _typed_aad(WRAP_AAD_DOMAIN, fields)


def _extensions_digest(extensions: dict[str, str | int | bool]) -> bytes:
    encoded = json.dumps(
        extensions,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).digest()


def _payload_aad(header: V3Header) -> bytes:
    return _typed_aad(
        PAYLOAD_AAD_DOMAIN,
        (
            ("format_version", _integer(header.format_version)),
            ("cipher", header.cipher.encode("ascii")),
            ("vault_id", UUID(header.vault_id).bytes),
            ("dek_id", UUID(header.dek_id).bytes),
            ("generation", _integer(header.generation)),
            ("payload_schema", _integer(header.payload_schema)),
            ("payload_nonce", header.payload_nonce),
            ("plaintext_length", _integer(header.plaintext_length)),
            ("ciphertext_length", _integer(header.ciphertext_length)),
            ("extensions_sha256", _extensions_digest(header.extensions)),
        ),
    )


def _json_depth(value: Any) -> int:
    def walk(current: Any, depth: int, ancestors: set[int]) -> int:
        if depth > MAX_JSON_DEPTH:
            return depth
        if not isinstance(current, (dict, list)):
            return depth
        identity = id(current)
        if identity in ancestors:
            raise V3PayloadError("V3 payload cannot contain a reference cycle")
        ancestors.add(identity)
        try:
            children = current.values() if isinstance(current, dict) else current
            return max(
                (walk(item, depth + 1, ancestors) for item in children),
                default=depth,
            )
        finally:
            ancestors.remove(identity)

    return walk(value, 1, set())


def _validate_payload(payload: Any) -> dict:
    if not isinstance(payload, dict):
        raise V3PayloadError("V3 payload must be a JSON object")
    if set(payload) != {"version", "entries"}:
        raise V3PayloadError("V3 payload schema 2 requires only version and entries")
    if payload.get("version") != 2 or isinstance(payload.get("version"), bool):
        raise V3PayloadError("V3 payload version must be 2")
    entries = payload.get("entries")
    if not isinstance(entries, dict) or len(entries) > MAX_ENTRY_COUNT:
        raise V3PayloadError("V3 entries must be an object within the entry limit")
    if _json_depth(payload) > MAX_JSON_DEPTH:
        raise V3PayloadError("V3 payload nesting exceeds the depth limit")
    _validate_json_values(payload)
    return payload


def _validate_json_values(value: Any) -> None:
    if value is None or isinstance(value, (bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise V3PayloadError("V3 payload is not finite JSON")
        return
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise V3PayloadError("V3 payload strings must be valid Unicode") from exc
        return
    if isinstance(value, list):
        for item in value:
            _validate_json_values(item)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise V3PayloadError("V3 payload object names must be strings")
            _validate_json_values(key)
            _validate_json_values(item)
        return
    raise V3PayloadError("V3 payload contains a non-JSON value")


def _serialize_payload(payload: dict) -> bytes:
    _validate_payload(payload)
    try:
        plaintext = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise V3PayloadError("V3 payload is not finite JSON") from exc
    if len(plaintext) + 16 > MAX_VAULT_BYTES:
        raise V3PayloadError("V3 plaintext exceeds the file resource limit")
    return plaintext


def validate_v3_payload(payload: dict) -> int:
    """Validate without deriving a key or writing; return canonical plaintext byte length."""

    return len(_serialize_payload(payload))


def _reject_duplicate_payload_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise V3PayloadError(f"Duplicate authenticated payload field: {key}")
        result[key] = value
    return result


def _reject_nonfinite_payload_constant(value: str) -> None:
    raise V3PayloadError(f"Authenticated payload contains non-finite JSON: {value}")


def _parse_plaintext(plaintext: bytes, expected_length: int) -> dict:
    if len(plaintext) != expected_length:
        raise V3PayloadError("Authenticated plaintext length mismatch")
    try:
        payload = json.loads(
            plaintext.decode("utf-8", errors="strict"),
            object_pairs_hook=_reject_duplicate_payload_fields,
            parse_constant=_reject_nonfinite_payload_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise V3PayloadError("Authenticated payload is not valid bounded JSON") from exc
    return _validate_payload(payload)


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _header_dict(header: V3Header) -> dict[str, Any]:
    def encode_slot(slot: KeySlotHeader) -> dict[str, Any]:
        common = {
            "slot_id": slot.slot_id,
            "wrap_cipher": slot.wrap_cipher,
            "wrap_nonce": _b64(slot.wrap_nonce),
            "wrapped_dek": _b64(slot.wrapped_dek),
        }
        if isinstance(slot, PasswordSlotHeader):
            return {
                **common,
                "type": "password",
                "kdf": {
                    "name": "argon2id",
                    "version": slot.kdf.version,
                    "memory_kib": slot.kdf.memory_kib,
                    "passes": slot.kdf.passes,
                    "lanes": slot.kdf.lanes,
                    "salt": _b64(slot.kdf.salt),
                    "output_bytes": slot.kdf.output_bytes,
                },
            }
        return {
            **common,
            "type": "device",
            "keyring_backend": slot.keyring_backend,
        }

    value: dict[str, Any] = {
        "format_version": header.format_version,
        "vault_id": header.vault_id,
        "generation": header.generation,
        "key_generation": header.key_generation,
        "payload_schema": header.payload_schema,
        "cipher": header.cipher,
        "payload_nonce": _b64(header.payload_nonce),
        "plaintext_length": header.plaintext_length,
        "ciphertext_length": header.ciphertext_length,
        "dek_id": header.dek_id,
        "key_slots": [encode_slot(slot) for slot in header.key_slots],
    }
    if header.extensions:
        value["extensions"] = header.extensions
    return value


def _assemble_frame(header: V3Header, ciphertext: bytes) -> bytes:
    raw_header = json.dumps(
        _header_dict(header),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    frame = V3_MAGIC + len(raw_header).to_bytes(4, "big") + raw_header + ciphertext
    parsed = parse_vault_container(frame)
    if not isinstance(parsed, V3Container):  # pragma: no cover - invariant guard
        raise V3CryptoError("Generated V3 frame was not recognized")
    return frame


def _base_header(
    *,
    materials: V3CreationMaterials,
    generation: int,
    key_generation: int,
    plaintext_length: int,
    ciphertext_length: int,
    key_slots: tuple[KeySlotHeader, ...] = (),
    extensions: dict[str, str | int | bool] | None = None,
) -> V3Header:
    return V3Header(
        format_version=3,
        vault_id=materials.vault_id,
        generation=generation,
        key_generation=key_generation,
        payload_schema=2,
        cipher="AES-256-GCM",
        payload_nonce=materials.payload_nonce,
        plaintext_length=plaintext_length,
        ciphertext_length=ciphertext_length,
        dek_id=materials.dek_id,
        key_slots=key_slots,
        extensions=dict(extensions or {}),
    )


def _password_slot(
    materials: V3CreationMaterials,
    *,
    wrapped_dek: bytes = b"",
) -> PasswordSlotHeader:
    return PasswordSlotHeader(
        slot_id=materials.slot_id,
        kdf=Argon2idParameters(
            version=ARGON2_VERSION,
            memory_kib=DEFAULT_MEMORY_KIB,
            passes=DEFAULT_PASSES,
            lanes=DEFAULT_LANES,
            salt=materials.salt,
            output_bytes=KEY_BYTES,
        ),
        wrap_cipher="AES-256-GCM",
        wrap_nonce=materials.wrap_nonce,
        wrapped_dek=wrapped_dek,
    )


def _wrap_dek(password: str, header: V3Header, slot: PasswordSlotHeader, dek: bytes) -> bytes:
    kek = _derive_kek(password, slot.kdf)
    try:
        return AESGCM(kek).encrypt(slot.wrap_nonce, dek, _wrap_aad(header, slot))
    finally:
        # Python bytes are immutable, so complete zeroization cannot be guaranteed.
        del kek


def _fresh_password_slot(slot_id: str) -> PasswordSlotHeader:
    return PasswordSlotHeader(
        slot_id=slot_id,
        kdf=Argon2idParameters(
            version=ARGON2_VERSION,
            memory_kib=DEFAULT_MEMORY_KIB,
            passes=DEFAULT_PASSES,
            lanes=DEFAULT_LANES,
            salt=os.urandom(SALT_BYTES),
            output_bytes=KEY_BYTES,
        ),
        wrap_cipher="AES-256-GCM",
        wrap_nonce=os.urandom(NONCE_BYTES),
        wrapped_dek=b"",
    )


def _wrap_device_dek(
    key: bytes, header: V3Header, slot: DeviceSlotHeader, dek: bytes
) -> bytes:
    if not isinstance(key, bytes) or len(key) != KEY_BYTES:
        raise V3CryptoError("Device key must be exactly 32 bytes")
    return AESGCM(key).encrypt(slot.wrap_nonce, dek, _wrap_aad(header, slot))


def _device_slot(
    slot_id: str,
    *,
    wrap_nonce: bytes | None = None,
    wrapped_dek: bytes = b"",
) -> DeviceSlotHeader:
    return DeviceSlotHeader(
        slot_id=slot_id,
        keyring_backend=WINDOWS_DEVICE_KEYRING_BACKEND,
        wrap_cipher="AES-256-GCM",
        wrap_nonce=wrap_nonce or os.urandom(NONCE_BYTES),
        wrapped_dek=wrapped_dek,
    )


def _password_slots(header: V3Header) -> tuple[PasswordSlotHeader, ...]:
    return tuple(
        slot for slot in header.key_slots if isinstance(slot, PasswordSlotHeader)
    )


def _device_slots(header: V3Header) -> tuple[DeviceSlotHeader, ...]:
    return tuple(slot for slot in header.key_slots if isinstance(slot, DeviceSlotHeader))


def _unlock_dek(credential: V3Credential, container: V3Container) -> bytes:
    if isinstance(credential, str):
        slots = _password_slots(container.header)
        if len(slots) != 1:
            raise V3PasswordSlotSelectionRequired(
                "Exactly one password slot is required for password unlock"
            )
        slot = slots[0]
        kek = _derive_kek(credential, slot.kdf)
        failure = "Wrong password or tampered V3 key slot"
    elif isinstance(credential, V3DeviceCredential):
        slots = tuple(
            slot
            for slot in _device_slots(container.header)
            if slot.slot_id == credential.slot_id
        )
        if len(slots) != 1:
            raise V3AuthenticationError("Device key slot is missing or ambiguous")
        slot = slots[0]
        kek = credential.key
        failure = "Wrong device key or tampered V3 key slot"
    else:
        raise TypeError("V3 credential must be a password or device credential")
    try:
        dek = AESGCM(kek).decrypt(
            slot.wrap_nonce,
            slot.wrapped_dek,
            _wrap_aad(container.header, slot),
        )
    except InvalidTag as exc:
        raise V3AuthenticationError(failure) from exc
    finally:
        if isinstance(credential, str):
            del kek
    if len(dek) != KEY_BYTES:
        raise V3AuthenticationError("Unwrapped V3 data key has the wrong length")
    return dek


def _decrypt_with_dek(container: V3Container, dek: bytes) -> dict:
    try:
        plaintext = AESGCM(dek).decrypt(
            container.header.payload_nonce,
            container.ciphertext,
            _payload_aad(container.header),
        )
    except InvalidTag as exc:
        raise V3AuthenticationError("Wrong password or tampered V3 payload") from exc
    return _parse_plaintext(plaintext, container.header.plaintext_length)


def decrypt_v3_payload(credential: V3Credential, value: bytes | V3Container) -> dict:
    container = parse_vault_container(value) if isinstance(value, bytes) else value
    if not isinstance(container, V3Container):
        raise V3CryptoError("Expected a Vault Format v3 container")
    dek = _unlock_dek(credential, container)
    try:
        return _decrypt_with_dek(container, dek)
    finally:
        del dek


def add_v3_device_slot(
    password: str,
    credential: V3DeviceCredential,
    value: bytes | V3Container,
) -> bytes:
    """Authenticate with the password and add one device-wrapped DEK slot."""

    container = parse_vault_container(value) if isinstance(value, bytes) else value
    if not isinstance(container, V3Container):
        raise V3CryptoError("Expected a Vault Format v3 container")
    if _device_slots(container.header):
        raise V3CryptoError("A device key slot is already enabled")
    password_slots = _password_slots(container.header)
    if len(password_slots) != 1:
        raise V3PasswordSlotSelectionRequired(
            "Exactly one password slot is required to enable device unlock"
        )
    if container.header.key_generation >= 2**63 - 1:
        raise V3CryptoError("V3 key generation is exhausted")
    dek = _unlock_dek(password, container)
    try:
        _decrypt_with_dek(container, dek)
        password_slot = _fresh_password_slot(password_slots[0].slot_id)
        device_slot = _device_slot(credential.slot_id)
        header = replace(
            container.header,
            key_generation=container.header.key_generation + 1,
            key_slots=(password_slot, device_slot),
        )
        password_slot = replace(
            password_slot,
            wrapped_dek=_wrap_dek(password, header, password_slot, dek),
        )
        device_slot = replace(
            device_slot,
            wrapped_dek=_wrap_device_dek(credential.key, header, device_slot, dek),
        )
        frame = _assemble_frame(
            replace(header, key_slots=(password_slot, device_slot)),
            container.ciphertext,
        )
        decrypt_v3_payload(password, frame)
        decrypt_v3_payload(credential, frame)
        return frame
    finally:
        del dek


def remove_v3_device_slot(
    password: str,
    slot_id: str,
    value: bytes | V3Container,
) -> bytes:
    """Authenticate with the password and return a password-only v3 frame."""

    container = parse_vault_container(value) if isinstance(value, bytes) else value
    if not isinstance(container, V3Container):
        raise V3CryptoError("Expected a Vault Format v3 container")
    device_slots = _device_slots(container.header)
    if len(device_slots) != 1 or device_slots[0].slot_id != slot_id:
        raise V3CryptoError("Requested device key slot is not enabled")
    password_slots = _password_slots(container.header)
    if len(password_slots) != 1:
        raise V3PasswordSlotSelectionRequired(
            "Exactly one password slot is required to disable device unlock"
        )
    if container.header.key_generation >= 2**63 - 1:
        raise V3CryptoError("V3 key generation is exhausted")
    dek = _unlock_dek(password, container)
    try:
        _decrypt_with_dek(container, dek)
        password_slot = _fresh_password_slot(password_slots[0].slot_id)
        header = replace(
            container.header,
            key_generation=container.header.key_generation + 1,
            key_slots=(password_slot,),
        )
        password_slot = replace(
            password_slot,
            wrapped_dek=_wrap_dek(password, header, password_slot, dek),
        )
        frame = _assemble_frame(
            replace(header, key_slots=(password_slot,)), container.ciphertext
        )
        decrypt_v3_payload(password, frame)
        return frame
    finally:
        del dek


def update_v3_extensions(
    credential: V3Credential,
    value: bytes | V3Container,
    extensions: dict[str, str | int | bool],
) -> bytes:
    """Authenticate and replace authenticated extensions with a fresh payload nonce."""

    container = parse_vault_container(value) if isinstance(value, bytes) else value
    if not isinstance(container, V3Container):
        raise V3CryptoError("Expected a Vault Format v3 container")
    payload = decrypt_v3_payload(credential, container)
    plaintext = _serialize_payload(payload)
    dek = _unlock_dek(credential, container)
    try:
        if container.header.generation >= 2**63 - 1:
            raise V3CryptoError("V3 content generation is exhausted")
        nonce = _fresh_payload_nonce(container.header.payload_nonce)
        header = replace(
            container.header,
            generation=container.header.generation + 1,
            payload_nonce=nonce,
            plaintext_length=len(plaintext),
            ciphertext_length=len(plaintext) + 16,
            extensions=dict(extensions),
        )
        ciphertext = AESGCM(dek).encrypt(nonce, plaintext, _payload_aad(header))
        frame = _assemble_frame(header, ciphertext)
        decrypt_v3_payload(credential, frame)
        return frame
    finally:
        del dek


def _create_v3_container_with_materials(
    password: str,
    payload: dict,
    materials: V3CreationMaterials,
    *,
    generation: int = 1,
    key_generation: int = 1,
    extensions: dict[str, str | int | bool] | None = None,
) -> bytes:
    """Deterministic test helper; production callers use create_v3_container()."""

    _validate_materials(materials)
    plaintext = _serialize_payload(payload)
    slot = _password_slot(materials)
    header = _base_header(
        materials=materials,
        generation=generation,
        key_generation=key_generation,
        plaintext_length=len(plaintext),
        ciphertext_length=len(plaintext) + 16,
        key_slots=(slot,),
        extensions=extensions,
    )
    wrapped_dek = _wrap_dek(password, header, slot, materials.dek)
    slot = _password_slot(materials, wrapped_dek=wrapped_dek)
    header = _base_header(
        materials=materials,
        generation=generation,
        key_generation=key_generation,
        plaintext_length=len(plaintext),
        ciphertext_length=len(plaintext) + 16,
        key_slots=(slot,),
        extensions=extensions,
    )
    ciphertext = AESGCM(materials.dek).encrypt(
        materials.payload_nonce,
        plaintext,
        _payload_aad(header),
    )
    return _assemble_frame(header, ciphertext)


def create_v3_container(password: str, payload: dict) -> bytes:
    return _create_v3_container_with_materials(password, payload, _random_materials())


def _fresh_payload_nonce(previous: bytes, supplied: bytes | None = None) -> bytes:
    if supplied is not None:
        if not isinstance(supplied, bytes) or len(supplied) != NONCE_BYTES:
            raise V3CryptoError("Test payload nonce must be 12 bytes")
        if supplied == previous:
            raise V3CryptoError("Payload nonce reuse is forbidden")
        return supplied
    for _ in range(8):
        candidate = os.urandom(NONCE_BYTES)
        if candidate != previous:
            return candidate
    raise V3CryptoError("CSPRNG repeatedly returned the prior payload nonce")


def update_v3_container(
    credential: V3Credential,
    payload: dict,
    value: bytes | V3Container,
    *,
    _payload_nonce: bytes | None = None,
) -> bytes:
    container = parse_vault_container(value) if isinstance(value, bytes) else value
    if not isinstance(container, V3Container):
        raise V3CryptoError("Expected a Vault Format v3 container")
    if container.header.generation >= 2**63 - 1:
        raise V3CryptoError("V3 content generation is exhausted")
    plaintext = _serialize_payload(payload)
    dek = _unlock_dek(credential, container)
    try:
        # Authenticate the old payload before replacing it.
        _decrypt_with_dek(container, dek)
        nonce = _fresh_payload_nonce(container.header.payload_nonce, _payload_nonce)
        header = V3Header(
            format_version=3,
            vault_id=container.header.vault_id,
            generation=container.header.generation + 1,
            key_generation=container.header.key_generation,
            payload_schema=2,
            cipher="AES-256-GCM",
            payload_nonce=nonce,
            plaintext_length=len(plaintext),
            ciphertext_length=len(plaintext) + 16,
            dek_id=container.header.dek_id,
            key_slots=container.header.key_slots,
            extensions=dict(container.header.extensions),
        )
        ciphertext = AESGCM(dek).encrypt(nonce, plaintext, _payload_aad(header))
        return _assemble_frame(header, ciphertext)
    finally:
        del dek


def rotate_v3_password(
    old_password: str,
    new_password: str,
    value: bytes | V3Container,
    *,
    _materials: V3CreationMaterials | None = None,
) -> bytes:
    container = parse_vault_container(value) if isinstance(value, bytes) else value
    if not isinstance(container, V3Container):
        raise V3CryptoError("Expected a Vault Format v3 container")
    if _device_slots(container.header):
        raise V3CryptoError(
            "Disable device unlock before rotating the password; "
            "device slots are never dropped implicitly"
        )
    if container.header.key_generation >= 2**63 - 1:
        raise V3CryptoError("V3 key generation is exhausted")
    dek = _unlock_dek(old_password, container)
    try:
        _decrypt_with_dek(container, dek)
        supplied = _materials or _random_materials(vault_id=container.header.vault_id)
        materials = V3CreationMaterials(
            vault_id=container.header.vault_id,
            dek_id=container.header.dek_id,
            slot_id=supplied.slot_id,
            salt=supplied.salt,
            wrap_nonce=supplied.wrap_nonce,
            payload_nonce=container.header.payload_nonce,
            dek=dek,
        )
        _validate_materials(materials)
        slot = _password_slot(materials)
        header = V3Header(
            format_version=3,
            vault_id=container.header.vault_id,
            generation=container.header.generation,
            key_generation=container.header.key_generation + 1,
            payload_schema=container.header.payload_schema,
            cipher=container.header.cipher,
            payload_nonce=container.header.payload_nonce,
            plaintext_length=container.header.plaintext_length,
            ciphertext_length=container.header.ciphertext_length,
            dek_id=container.header.dek_id,
            key_slots=(slot,),
            extensions=dict(container.header.extensions),
        )
        slot = _password_slot(
            materials,
            wrapped_dek=_wrap_dek(new_password, header, slot, dek),
        )
        header = replace(header, key_slots=(slot,))
        frame = _assemble_frame(header, container.ciphertext)
        decrypt_v3_payload(new_password, frame)
        return frame
    finally:
        del dek


def rotate_v3_dek(
    password: str,
    value: bytes | V3Container,
    *,
    _materials: V3CreationMaterials | None = None,
) -> bytes:
    container = parse_vault_container(value) if isinstance(value, bytes) else value
    if not isinstance(container, V3Container):
        raise V3CryptoError("Expected a Vault Format v3 container")
    if _device_slots(container.header):
        raise V3CryptoError(
            "Disable device unlock before rotating the data key; "
            "device slots are never dropped implicitly"
        )
    if (
        container.header.generation >= 2**63 - 1
        or container.header.key_generation >= 2**63 - 1
    ):
        raise V3CryptoError("V3 content or key generation is exhausted")
    old_dek = _unlock_dek(password, container)
    try:
        payload = _decrypt_with_dek(container, old_dek)
    finally:
        del old_dek
    materials = _materials or _random_materials(vault_id=container.header.vault_id)
    if materials.vault_id != container.header.vault_id:
        raise V3CryptoError("DEK rotation must preserve vault_id")
    return _create_v3_container_with_materials(
        password,
        payload,
        materials,
        generation=container.header.generation + 1,
        key_generation=container.header.key_generation + 1,
        extensions=container.header.extensions,
    )


def create_v3_file(path: Path, password: str, payload: dict) -> None:
    path = Path(path)
    require_clean_storage(path)
    if path.exists():
        raise FileExistsError(f"Vault already exists: {path}")
    frame = create_v3_container(password, payload)
    atomic_write_bytes(
        path,
        frame,
        validator=lambda candidate: decrypt_v3_payload(password, candidate),
        must_not_exist=True,
    )


def update_v3_file(path: Path, credential: V3Credential, payload: dict) -> None:
    path = Path(path)
    require_clean_storage(path)
    source = path.read_bytes()
    container = parse_vault_container(source)
    if not isinstance(container, V3Container):
        raise V3CryptoError("Refusing V3 update for a legacy file")
    frame = update_v3_container(credential, payload, container)
    atomic_write_bytes(
        path,
        frame,
        validator=lambda candidate: decrypt_v3_payload(credential, candidate),
        expected_old_sha256=hashlib.sha256(source).hexdigest(),
    )
    _advance_anchor_after_write(path, credential)


def rotate_v3_password_file(path: Path, old_password: str, new_password: str) -> None:
    path = Path(path)
    require_clean_storage(path)
    source = path.read_bytes()
    frame = rotate_v3_password(old_password, new_password, source)
    atomic_write_bytes(
        path,
        frame,
        validator=lambda candidate: decrypt_v3_payload(new_password, candidate),
        expected_old_sha256=hashlib.sha256(source).hexdigest(),
    )
    _advance_anchor_after_write(path, new_password)


def rotate_v3_dek_file(path: Path, password: str) -> None:
    path = Path(path)
    require_clean_storage(path)
    source = path.read_bytes()
    frame = rotate_v3_dek(password, source)
    atomic_write_bytes(
        path,
        frame,
        validator=lambda candidate: decrypt_v3_payload(password, candidate),
        expected_old_sha256=hashlib.sha256(source).hexdigest(),
    )
    _advance_anchor_after_write(path, password)


def _advance_anchor_after_write(path: Path, credential: V3Credential) -> None:
    container = parse_vault_container(Path(path).read_bytes())
    if not isinstance(container, V3Container) or not container.header.extensions.get(
        ROLLBACK_ANCHOR_EXTENSION, False
    ):
        return
    from vault_unified.device_keyring import verify_and_advance_rollback_anchor

    verify_and_advance_rollback_anchor(path, credential=credential)

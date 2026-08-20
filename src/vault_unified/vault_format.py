from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import UUID

from vault_unified.storage import require_clean_storage


V3_MAGIC = b"VLTUV3\r\n"
VAULT_FAMILY_PREFIX = b"VLTUV"
FIXED_PREFIX_BYTES = len(V3_MAGIC) + 4
MAX_HEADER_BYTES = 64 * 1024
MAX_VAULT_BYTES = 256 * 1024 * 1024
MAX_KEY_SLOTS = 8
MIN_ARGON2_MEMORY_KIB = 65_536
MAX_ARGON2_MEMORY_KIB = 262_144
MAX_ARGON2_PASSES = 6
MAX_ARGON2_LANES = 4
MAX_ARGON2_WORK = 786_432
SUPPORTED_PAYLOAD_SCHEMAS = frozenset({2})

_B64URL_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_EXTENSION_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]*:[a-z0-9_.-]+$")


class VaultKind(str, Enum):
    LEGACY = "legacy-v1-v2"
    V3 = "v3"


class VaultFormatError(ValueError):
    """A vault container is malformed or violates a resource bound."""


class UnsupportedVaultVersion(VaultFormatError):
    """A framed Vault Unified container version is not supported."""


class V3ReadOnlyError(VaultFormatError):
    """Deprecated compatibility exception retained for callers of the 5b preview."""


@dataclass(frozen=True)
class LegacyContainer:
    kind: VaultKind
    blob: bytes


@dataclass(frozen=True)
class Argon2idParameters:
    version: int
    memory_kib: int
    passes: int
    lanes: int
    salt: bytes
    output_bytes: int


@dataclass(frozen=True)
class PasswordSlotHeader:
    slot_id: str
    kdf: Argon2idParameters
    wrap_cipher: str
    wrap_nonce: bytes
    wrapped_dek: bytes


@dataclass(frozen=True)
class V3Header:
    format_version: int
    vault_id: str
    generation: int
    key_generation: int
    payload_schema: int
    cipher: str
    payload_nonce: bytes
    plaintext_length: int
    ciphertext_length: int
    dek_id: str
    key_slots: tuple[PasswordSlotHeader, ...]
    extensions: dict[str, str | int | bool]


@dataclass(frozen=True)
class V3Container:
    kind: VaultKind
    header: V3Header
    raw_header: bytes
    ciphertext: bytes


VaultContainer = LegacyContainer | V3Container


def _reject_duplicate_names(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise VaultFormatError(f"Duplicate JSON field: {key}")
        result[key] = value
    return result


def _exact_keys(
    value: dict[str, Any],
    required: set[str],
    optional: set[str] | None = None,
    *,
    context: str,
) -> None:
    optional = optional or set()
    keys = set(value)
    missing = required - keys
    unknown = keys - required - optional
    if missing:
        raise VaultFormatError(f"Missing {context} fields: {', '.join(sorted(missing))}")
    if unknown:
        raise VaultFormatError(f"Unknown {context} fields: {', '.join(sorted(unknown))}")


def _integer(value: Any, *, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise VaultFormatError(f"{name} must be an integer")
    if value < minimum or value > maximum:
        raise VaultFormatError(f"{name} is outside the accepted range")
    return value


def _canonical_uuid(value: Any, *, name: str) -> str:
    if not isinstance(value, str):
        raise VaultFormatError(f"{name} must be a UUID string")
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError) as exc:
        raise VaultFormatError(f"{name} is not a valid UUID") from exc
    canonical = str(parsed)
    if value != canonical:
        raise VaultFormatError(f"{name} must use canonical lowercase UUID encoding")
    return canonical


def _decode_base64url(value: Any, *, name: str, minimum: int, maximum: int) -> bytes:
    if not isinstance(value, str) or not _B64URL_RE.fullmatch(value):
        raise VaultFormatError(f"{name} must be unpadded canonical base64url")
    padding = "=" * ((4 - len(value) % 4) % 4)
    try:
        decoded = base64.b64decode(value + padding, altchars=b"-_", validate=True)
    except (ValueError, binascii.Error) as exc:
        raise VaultFormatError(f"{name} is invalid base64url") from exc
    canonical = base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii")
    if canonical != value or len(decoded) < minimum or len(decoded) > maximum:
        raise VaultFormatError(f"{name} has an invalid encoding or length")
    return decoded


def _parse_extensions(value: Any) -> dict[str, str | int | bool]:
    if value is None:
        return {}
    if not isinstance(value, dict) or len(value) > 16:
        raise VaultFormatError("extensions must be an object with at most 16 fields")
    parsed: dict[str, str | int | bool] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not _EXTENSION_KEY_RE.fullmatch(key):
            raise VaultFormatError("extension names must be lowercase and namespace-qualified")
        if isinstance(item, str):
            try:
                encoded = item.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise VaultFormatError(
                    f"extension value is not valid Unicode: {key}"
                ) from exc
            if len(encoded) > 1024:
                raise VaultFormatError(f"extension value is oversized: {key}")
        elif isinstance(item, bool):
            pass
        elif isinstance(item, int):
            if item < -(2**63) or item > 2**63 - 1:
                raise VaultFormatError(f"extension integer is out of range: {key}")
        else:
            raise VaultFormatError(f"unsupported extension value type: {key}")
        parsed[key] = item
    return parsed


def _parse_password_slot(value: Any) -> PasswordSlotHeader:
    if not isinstance(value, dict):
        raise VaultFormatError("key slot must be an object")
    _exact_keys(
        value,
        {"slot_id", "type", "kdf", "wrap_cipher", "wrap_nonce", "wrapped_dek"},
        context="key slot",
    )
    if value["type"] != "password":
        raise VaultFormatError("5b accepts password key slots only")
    if value["wrap_cipher"] != "AES-256-GCM":
        raise VaultFormatError("Unsupported DEK wrapping cipher")
    if not isinstance(value["kdf"], dict):
        raise VaultFormatError("kdf must be an object")
    kdf = value["kdf"]
    _exact_keys(
        kdf,
        {"name", "version", "memory_kib", "passes", "lanes", "salt", "output_bytes"},
        context="KDF",
    )
    if kdf["name"] != "argon2id":
        raise VaultFormatError("Unsupported password KDF")
    version = _integer(kdf["version"], name="Argon2 version", minimum=19, maximum=19)
    memory_kib = _integer(
        kdf["memory_kib"],
        name="Argon2 memory",
        minimum=MIN_ARGON2_MEMORY_KIB,
        maximum=MAX_ARGON2_MEMORY_KIB,
    )
    passes = _integer(
        kdf["passes"],
        name="Argon2 passes",
        minimum=1,
        maximum=MAX_ARGON2_PASSES,
    )
    lanes = _integer(
        kdf["lanes"],
        name="Argon2 lanes",
        minimum=1,
        maximum=MAX_ARGON2_LANES,
    )
    if memory_kib < 8 * lanes or memory_kib * passes > MAX_ARGON2_WORK:
        raise VaultFormatError("Argon2 parameters exceed the accepted work policy")
    output_bytes = _integer(
        kdf["output_bytes"],
        name="Argon2 output length",
        minimum=32,
        maximum=32,
    )
    return PasswordSlotHeader(
        slot_id=_canonical_uuid(value["slot_id"], name="slot_id"),
        kdf=Argon2idParameters(
            version=version,
            memory_kib=memory_kib,
            passes=passes,
            lanes=lanes,
            salt=_decode_base64url(kdf["salt"], name="KDF salt", minimum=16, maximum=32),
            output_bytes=output_bytes,
        ),
        wrap_cipher="AES-256-GCM",
        wrap_nonce=_decode_base64url(
            value["wrap_nonce"], name="wrap nonce", minimum=12, maximum=12
        ),
        wrapped_dek=_decode_base64url(
            value["wrapped_dek"], name="wrapped DEK", minimum=48, maximum=48
        ),
    )


def _parse_v3_header(raw_header: bytes, ciphertext_length: int) -> V3Header:
    try:
        text = raw_header.decode("utf-8", errors="strict")
        value = json.loads(text, object_pairs_hook=_reject_duplicate_names)
    except UnicodeDecodeError as exc:
        raise VaultFormatError("V3 header is not valid UTF-8") from exc
    except json.JSONDecodeError as exc:
        raise VaultFormatError("V3 header is not valid JSON") from exc
    if not isinstance(value, dict):
        raise VaultFormatError("V3 header must be a JSON object")
    _exact_keys(
        value,
        {
            "format_version",
            "vault_id",
            "generation",
            "key_generation",
            "payload_schema",
            "cipher",
            "payload_nonce",
            "plaintext_length",
            "ciphertext_length",
            "dek_id",
            "key_slots",
        },
        {"extensions"},
        context="V3 header",
    )
    format_version = _integer(
        value["format_version"], name="format_version", minimum=3, maximum=3
    )
    generation = _integer(
        value["generation"], name="generation", minimum=1, maximum=2**63 - 1
    )
    key_generation = _integer(
        value["key_generation"], name="key_generation", minimum=1, maximum=2**63 - 1
    )
    payload_schema = _integer(
        value["payload_schema"], name="payload_schema", minimum=1, maximum=2**31 - 1
    )
    if payload_schema not in SUPPORTED_PAYLOAD_SCHEMAS:
        raise VaultFormatError(f"Unsupported payload schema: {payload_schema}")
    if value["cipher"] != "AES-256-GCM":
        raise VaultFormatError("Unsupported payload cipher")
    declared_length = _integer(
        value["ciphertext_length"],
        name="ciphertext_length",
        minimum=16,
        maximum=MAX_VAULT_BYTES,
    )
    if declared_length != ciphertext_length:
        raise VaultFormatError("Declared ciphertext length does not match the frame")
    plaintext_length = _integer(
        value["plaintext_length"],
        name="plaintext_length",
        minimum=2,
        maximum=MAX_VAULT_BYTES,
    )
    if plaintext_length + 16 != declared_length:
        raise VaultFormatError("Plaintext and ciphertext lengths are inconsistent")
    if not isinstance(value["key_slots"], list):
        raise VaultFormatError("key_slots must be an array")
    if not 1 <= len(value["key_slots"]) <= MAX_KEY_SLOTS:
        raise VaultFormatError("key_slots count is outside the accepted range")
    slots = tuple(_parse_password_slot(slot) for slot in value["key_slots"])
    slot_ids = [slot.slot_id for slot in slots]
    if len(slot_ids) != len(set(slot_ids)):
        raise VaultFormatError("Duplicate key slot ID")
    return V3Header(
        format_version=format_version,
        vault_id=_canonical_uuid(value["vault_id"], name="vault_id"),
        generation=generation,
        key_generation=key_generation,
        payload_schema=payload_schema,
        cipher="AES-256-GCM",
        payload_nonce=_decode_base64url(
            value["payload_nonce"], name="payload nonce", minimum=12, maximum=12
        ),
        plaintext_length=plaintext_length,
        ciphertext_length=declared_length,
        dek_id=_canonical_uuid(value["dek_id"], name="dek_id"),
        key_slots=slots,
        extensions=_parse_extensions(value.get("extensions")),
    )


def parse_vault_container(blob: bytes) -> VaultContainer:
    """Classify legacy bytes or strictly parse a v3 frame without decrypting it."""

    if not isinstance(blob, bytes):
        raise TypeError("Vault container must be bytes")
    if len(blob) > MAX_VAULT_BYTES:
        raise VaultFormatError("Vault file exceeds the 256 MiB hard limit")
    if not blob.startswith(VAULT_FAMILY_PREFIX):
        return LegacyContainer(kind=VaultKind.LEGACY, blob=blob)
    if not blob.startswith(V3_MAGIC):
        raise UnsupportedVaultVersion("Unknown or damaged Vault Unified framed version")
    if len(blob) < FIXED_PREFIX_BYTES:
        raise VaultFormatError("Truncated V3 fixed prefix")
    header_length = int.from_bytes(blob[len(V3_MAGIC) : FIXED_PREFIX_BYTES], "big")
    if header_length < 2 or header_length > MAX_HEADER_BYTES:
        raise VaultFormatError("V3 header length is outside the accepted range")
    header_end = FIXED_PREFIX_BYTES + header_length
    if header_end > len(blob):
        raise VaultFormatError("Truncated V3 header")
    raw_header = blob[FIXED_PREFIX_BYTES:header_end]
    ciphertext = blob[header_end:]
    header = _parse_v3_header(raw_header, len(ciphertext))
    return V3Container(
        kind=VaultKind.V3,
        header=header,
        raw_header=raw_header,
        ciphertext=ciphertext,
    )


def inspect_vault_format_file(path: Path) -> VaultContainer:
    """Read-only file inspection with size and interrupted-write checks."""

    path = Path(path)
    require_clean_storage(path)
    if path.stat().st_size > MAX_VAULT_BYTES:
        raise VaultFormatError("Vault file exceeds the 256 MiB hard limit")
    return parse_vault_container(path.read_bytes())


def is_framed_vault_file(path: Path) -> bool:
    """Classify only the family prefix for keyring-boundary decisions; never writes."""

    path = Path(path)
    if not path.exists():
        return False
    with path.open("rb") as handle:
        return handle.read(len(VAULT_FAMILY_PREFIX)) == VAULT_FAMILY_PREFIX


def describe_vault_container(container: VaultContainer) -> dict[str, Any]:
    """Return non-secret format metadata suitable for CLI/API diagnostics."""

    if isinstance(container, LegacyContainer):
        return {
            "kind": container.kind.value,
            "container_version": "legacy",
            "authenticated": False,
        }
    return {
        "kind": container.kind.value,
        "container_version": container.header.format_version,
        "authenticated": False,
        "payload_schema": container.header.payload_schema,
        "generation": container.header.generation,
        "key_generation": container.header.key_generation,
        "vault_id": container.header.vault_id,
        "cipher": container.header.cipher,
        "key_slot_count": len(container.header.key_slots),
        "key_slot_types": ["password" for _ in container.header.key_slots],
        "kdf": "argon2id",
    }

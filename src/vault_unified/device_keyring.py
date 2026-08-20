from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from vault_unified.storage import atomic_write_bytes, require_clean_storage
from vault_unified.v3_crypto import (
    KEY_BYTES,
    ROLLBACK_ANCHOR_EXTENSION,
    V3Credential,
    V3DeviceCredential,
    add_v3_device_slot,
    decrypt_v3_payload,
    remove_v3_device_slot,
    update_v3_extensions,
)
from vault_unified.vault_format import (
    DeviceSlotHeader,
    V3Container,
    VaultFormatError,
    parse_vault_container,
)


DEVICE_SERVICE = "vault-unified:v3-device"
ANCHOR_SERVICE = "vault-unified:v3-rollback-anchor"
APPROVED_WINDOWS_BACKEND = ("keyring.backends.Windows", "WinVaultKeyring")


class KeyringBackend(Protocol):
    def get_password(self, service: str, username: str) -> str | None: ...

    def set_password(self, service: str, username: str, password: str) -> None: ...

    def delete_password(self, service: str, username: str) -> None: ...


class DeviceKeyringError(RuntimeError):
    """A device-key or rollback-anchor operation failed without exposing key material."""


class UnapprovedKeyringBackend(DeviceKeyringError):
    """The active backend is not the reviewed Windows Credential Manager backend."""


class DeviceKeyringCleanupRequired(DeviceKeyringError):
    """The vault is safe, but an external keyring record needs manual cleanup."""


class V3RollbackDetected(DeviceKeyringError):
    """An authenticated vault is older than, or conflicts with, its rollback anchor."""


@dataclass(frozen=True)
class RollbackAnchor:
    vault_id: str
    generation: int
    key_generation: int
    file_sha256: str

    def encode(self) -> str:
        return json.dumps(
            {
                "version": 1,
                "vault_id": self.vault_id,
                "generation": self.generation,
                "key_generation": self.key_generation,
                "file_sha256": self.file_sha256,
            },
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def decode(cls, value: str) -> RollbackAnchor:
        try:
            parsed = json.loads(value)
        except (TypeError, json.JSONDecodeError) as exc:
            raise DeviceKeyringError("Rollback anchor is malformed") from exc
        if not isinstance(parsed, dict) or set(parsed) != {
            "version",
            "vault_id",
            "generation",
            "key_generation",
            "file_sha256",
        }:
            raise DeviceKeyringError("Rollback anchor has an invalid schema")
        if parsed["version"] != 1:
            raise DeviceKeyringError("Rollback anchor version is unsupported")
        if (
            not isinstance(parsed["generation"], int)
            or isinstance(parsed["generation"], bool)
            or parsed["generation"] < 1
            or not isinstance(parsed["key_generation"], int)
            or isinstance(parsed["key_generation"], bool)
            or parsed["key_generation"] < 1
        ):
            raise DeviceKeyringError("Rollback anchor generations are invalid")
        digest = parsed["file_sha256"]
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise DeviceKeyringError("Rollback anchor digest is invalid")
        if not isinstance(parsed["vault_id"], str):
            raise DeviceKeyringError("Rollback anchor vault ID is invalid")
        return cls(
            vault_id=parsed["vault_id"],
            generation=parsed["generation"],
            key_generation=parsed["key_generation"],
            file_sha256=digest,
        )


def validate_production_backend(
    backend: KeyringBackend, *, system_name: str | None = None
) -> KeyringBackend:
    """Allow only the exact reviewed core Windows backend, never a configured substitute."""

    if (system_name or platform.system()) != "Windows":
        raise UnapprovedKeyringBackend("Device keyring is supported on Windows only")
    backend_type = type(backend)
    identity = (backend_type.__module__, backend_type.__name__)
    if identity != APPROVED_WINDOWS_BACKEND:
        raise UnapprovedKeyringBackend(
            "Active keyring backend is not the approved Windows Credential Manager backend"
        )
    return backend


def get_approved_backend() -> KeyringBackend:
    import keyring

    return validate_production_backend(keyring.get_keyring())


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode_device_key(value: str | None) -> bytes:
    if not isinstance(value, str) or not value or "=" in value:
        raise DeviceKeyringError("Device keyring record is missing or invalid")
    try:
        decoded = base64.b64decode(
            value + "=" * ((4 - len(value) % 4) % 4),
            altchars=b"-_",
            validate=True,
        )
    except (ValueError, TypeError) as exc:
        raise DeviceKeyringError("Device keyring record is missing or invalid") from exc
    if len(decoded) != KEY_BYTES or _b64(decoded) != value:
        raise DeviceKeyringError("Device keyring record is missing or invalid")
    return decoded


def _v3(path: Path) -> tuple[bytes, V3Container]:
    require_clean_storage(path)
    source = Path(path).read_bytes()
    container = parse_vault_container(source)
    if not isinstance(container, V3Container):
        raise VaultFormatError("Device keyring operations require Vault Format v3")
    return source, container


def _device_slots(container: V3Container) -> tuple[DeviceSlotHeader, ...]:
    return tuple(
        slot for slot in container.header.key_slots if isinstance(slot, DeviceSlotHeader)
    )


def _device_account(vault_id: str, slot_id: str) -> str:
    return f"{vault_id}:{slot_id}"


def device_slot_metadata(path: Path) -> dict[str, str] | None:
    """Inspect only public file metadata; this function never opens the keyring."""

    _, container = _v3(Path(path))
    slots = _device_slots(container)
    if not slots:
        return None
    if len(slots) != 1:  # pragma: no cover - parser invariant
        raise DeviceKeyringError("Device key slot is ambiguous")
    return {
        "vault_id": container.header.vault_id,
        "slot_id": slots[0].slot_id,
        "keyring_backend": slots[0].keyring_backend,
    }


def load_device_credential(path: Path) -> V3DeviceCredential:
    _, container = _v3(Path(path))
    slots = _device_slots(container)
    if len(slots) != 1:
        raise DeviceKeyringError("Exactly one device key slot must be enabled")
    slot = slots[0]
    backend = get_approved_backend()
    try:
        encoded = backend.get_password(
            DEVICE_SERVICE, _device_account(container.header.vault_id, slot.slot_id)
        )
    except Exception as exc:
        raise DeviceKeyringError("Unable to read the device keyring record") from exc
    return V3DeviceCredential(slot_id=slot.slot_id, key=_decode_device_key(encoded))


def device_unlock_available(path: Path) -> bool:
    try:
        credential = load_device_credential(path)
        decrypt_v3_payload(credential, Path(path).read_bytes())
        return True
    except Exception:
        return False


def enable_device_unlock(path: Path, password: str) -> V3DeviceCredential:
    path = Path(path)
    source, container = _v3(path)
    if _device_slots(container):
        credential = load_device_credential(path)
        decrypt_v3_payload(credential, container)
        return credential
    backend = get_approved_backend()
    credential = V3DeviceCredential(slot_id=str(uuid4()), key=os.urandom(KEY_BYTES))
    account = _device_account(container.header.vault_id, credential.slot_id)
    frame = add_v3_device_slot(password, credential, container)
    try:
        backend.set_password(DEVICE_SERVICE, account, _b64(credential.key))
    except Exception as exc:
        raise DeviceKeyringError("Unable to create the device keyring record") from exc
    try:
        atomic_write_bytes(
            path,
            frame,
            validator=lambda candidate: (
                decrypt_v3_payload(password, candidate),
                decrypt_v3_payload(credential, candidate),
            ),
            expected_old_sha256=hashlib.sha256(source).hexdigest(),
        )
    except Exception as write_exc:
        try:
            backend.delete_password(DEVICE_SERVICE, account)
        except Exception as cleanup_exc:
            raise DeviceKeyringCleanupRequired(
                "Device enable failed; remove the orphan device record manually"
            ) from cleanup_exc
        raise DeviceKeyringError("Device enable failed before vault activation") from write_exc
    verify_and_advance_rollback_anchor(path, credential=credential)
    return credential


def disable_device_unlock(path: Path, password: str) -> None:
    path = Path(path)
    source, container = _v3(path)
    slots = _device_slots(container)
    if len(slots) != 1:
        raise DeviceKeyringError("Exactly one device key slot must be enabled")
    slot = slots[0]
    backend = get_approved_backend()
    account = _device_account(container.header.vault_id, slot.slot_id)
    frame = remove_v3_device_slot(password, slot.slot_id, container)
    atomic_write_bytes(
        path,
        frame,
        validator=lambda candidate: decrypt_v3_payload(password, candidate),
        expected_old_sha256=hashlib.sha256(source).hexdigest(),
    )
    try:
        backend.delete_password(DEVICE_SERVICE, account)
    except Exception as exc:
        raise DeviceKeyringCleanupRequired(
            "Device slot is disabled; remove the orphan device record manually"
        ) from exc
    verify_and_advance_rollback_anchor(path, credential=password)


def _anchor_for(blob: bytes, container: V3Container) -> RollbackAnchor:
    return RollbackAnchor(
        vault_id=container.header.vault_id,
        generation=container.header.generation,
        key_generation=container.header.key_generation,
        file_sha256=hashlib.sha256(blob).hexdigest(),
    )


def verify_and_advance_rollback_anchor(
    path: Path, *, credential: V3Credential
) -> bool:
    """Verify an enabled anchor after authentication; absence degrades without data loss."""

    path = Path(path)
    blob, container = _v3(path)
    if container.header.extensions.get(ROLLBACK_ANCHOR_EXTENSION) is not True:
        return False
    decrypt_v3_payload(credential, container)
    try:
        backend = get_approved_backend()
        encoded = backend.get_password(ANCHOR_SERVICE, container.header.vault_id)
    except UnapprovedKeyringBackend:
        return False
    except Exception:
        return False
    if encoded is None:
        return False
    stored = RollbackAnchor.decode(encoded)
    current = _anchor_for(blob, container)
    if stored.vault_id != current.vault_id:
        raise V3RollbackDetected("Rollback anchor belongs to a different vault")
    if (
        current.generation < stored.generation
        or current.key_generation < stored.key_generation
    ):
        raise V3RollbackDetected("Vault rollback detected")
    if (
        current.generation == stored.generation
        and current.key_generation == stored.key_generation
    ):
        if current.file_sha256 != stored.file_sha256:
            raise V3RollbackDetected("Vault digest conflicts with rollback anchor")
        return True
    try:
        backend.set_password(ANCHOR_SERVICE, current.vault_id, current.encode())
    except Exception as exc:
        raise DeviceKeyringError("Unable to advance rollback anchor") from exc
    return True


def enable_rollback_anchor(path: Path, credential: V3Credential) -> RollbackAnchor:
    path = Path(path)
    source, container = _v3(path)
    backend = get_approved_backend()
    extensions = dict(container.header.extensions)
    extensions[ROLLBACK_ANCHOR_EXTENSION] = True
    frame = update_v3_extensions(credential, container, extensions)
    atomic_write_bytes(
        path,
        frame,
        validator=lambda candidate: decrypt_v3_payload(credential, candidate),
        expected_old_sha256=hashlib.sha256(source).hexdigest(),
    )
    activated = parse_vault_container(frame)
    if not isinstance(activated, V3Container):  # pragma: no cover - invariant guard
        raise DeviceKeyringError("Anchor candidate was not Vault Format v3")
    anchor = _anchor_for(frame, activated)
    try:
        backend.set_password(ANCHOR_SERVICE, anchor.vault_id, anchor.encode())
    except Exception as exc:
        raise DeviceKeyringError(
            "Vault remains recoverable, but rollback anchor creation failed"
        ) from exc
    return anchor


def disable_rollback_anchor(path: Path, credential: V3Credential) -> None:
    path = Path(path)
    source, container = _v3(path)
    backend = get_approved_backend()
    extensions = dict(container.header.extensions)
    extensions.pop(ROLLBACK_ANCHOR_EXTENSION, None)
    frame = update_v3_extensions(credential, container, extensions)
    atomic_write_bytes(
        path,
        frame,
        validator=lambda candidate: decrypt_v3_payload(credential, candidate),
        expected_old_sha256=hashlib.sha256(source).hexdigest(),
    )
    try:
        backend.delete_password(ANCHOR_SERVICE, container.header.vault_id)
    except Exception as exc:
        raise DeviceKeyringCleanupRequired(
            "Rollback enforcement is disabled; remove the orphan anchor manually"
        ) from exc


def inspect_rollback_anchor(path: Path) -> dict[str, object]:
    """Return non-secret anchor metadata. The device KEK is never accessed."""

    _, container = _v3(Path(path))
    marked = container.header.extensions.get(ROLLBACK_ANCHOR_EXTENSION) is True
    result: dict[str, object] = {
        "enabled_in_vault": marked,
        "vault_id": container.header.vault_id,
        "generation": container.header.generation,
        "key_generation": container.header.key_generation,
        "anchor_present": False,
    }
    if not marked:
        return result
    try:
        encoded = get_approved_backend().get_password(
            ANCHOR_SERVICE, container.header.vault_id
        )
    except Exception:
        return result
    if encoded is None:
        return result
    anchor = RollbackAnchor.decode(encoded)
    result.update(
        anchor_present=True,
        anchor_generation=anchor.generation,
        anchor_key_generation=anchor.key_generation,
        digest_matches=anchor.file_sha256
        == hashlib.sha256(Path(path).read_bytes()).hexdigest(),
    )
    return result

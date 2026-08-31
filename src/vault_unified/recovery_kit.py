"""Offline emergency recovery kits for a personal Vault Unified vault.

A recovery kit is a separate v3 vault encrypted with a high-entropy recovery
code.  It is not a backdoor and it is not stored in the Windows keyring: the
user must place the encrypted kit and the recovery code in separate locations.
"""

from __future__ import annotations

import secrets
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from vault_unified.config import get_config_dir
from vault_unified.crypto import decrypt_payload
from vault_unified.models import SecretEntry
from vault_unified.storage import atomic_write_bytes, require_clean_storage
from vault_unified.v3_crypto import create_v3_file


RECOVERY_CODE_MIN_LENGTH = 32


def generate_recovery_code() -> str:
    """Return a printable, high-entropy code; callers must display it only once."""
    return "VU-RK-" + secrets.token_urlsafe(32)


def _validate_code(value: str) -> str:
    if not isinstance(value, str) or len(value) < RECOVERY_CODE_MIN_LENGTH:
        raise ValueError("Recovery code is too short")
    if len(value) > 512:
        raise ValueError("Recovery code is too long")
    return value


def default_recovery_dir() -> Path:
    return get_config_dir().parent / "recovery"


def _portable_payload(vault: object) -> dict:
    """Rebuild a current v2 payload without changing the active vault bytes."""
    return {
        "version": 2,
        "entries": {
            entry_id: entry.to_dict()
            for entry_id, entry in vault.local._entries.items()
        },
    }


def create_recovery_kit(
    vault: object,
    recovery_code: str,
    destination_dir: str | Path | None = None,
) -> Path:
    code = _validate_code(recovery_code)
    destination = Path(destination_dir).expanduser() if destination_dir else default_recovery_dir()
    destination = destination.resolve()
    if destination.exists() and (destination.is_symlink() or not destination.is_dir()):
        raise ValueError("Recovery-kit destination must be a regular directory")
    destination.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = destination / f"VaultUnified-recovery-{stamp}.vault"
    counter = 1
    while path.exists():
        path = destination / f"VaultUnified-recovery-{stamp}-{counter}.vault"
        counter += 1
    create_v3_file(path, code, _portable_payload(vault))
    # A successful v3 write is authenticated by create_v3_file's own validator.
    decrypt_payload(code, path.read_bytes())
    return path


def inspect_recovery_kit(kit_path: str | Path, recovery_code: str) -> dict:
    """Authenticate and parse a kit without writing the active vault."""

    code = _validate_code(recovery_code)
    source = Path(kit_path).expanduser().resolve()
    if source.is_symlink() or not source.is_file():
        raise FileNotFoundError("Recovery kit was not found")
    data = source.read_bytes()
    payload = decrypt_payload(code, data)
    if (
        not isinstance(payload, dict)
        or payload.get("version") != 2
        or not isinstance(payload.get("entries"), dict)
    ):
        raise ValueError("Recovery kit has an unsupported payload")
    for entry_id, entry in payload["entries"].items():
        if not isinstance(entry_id, str) or not isinstance(entry, dict):
            raise ValueError("Recovery kit entry schema is invalid")
        SecretEntry.from_dict(entry)
    stat = source.stat()
    return {
        "path": str(source),
        "size": len(data),
        "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        "sha256": hashlib.sha256(data).hexdigest(),
        "format": "v3",
        "entry_count": len(payload["entries"]),
    }


def restore_from_recovery_kit(
    target_path: Path,
    kit_path: str | Path,
    recovery_code: str,
    new_password: str,
    *,
    expected_target_sha256: str | None = None,
    expected_kit_sha256: str | None = None,
) -> None:
    """Replace the active vault with kit contents encrypted under a new password."""
    code = _validate_code(recovery_code)
    if not isinstance(new_password, str) or not new_password:
        raise ValueError("A new master password is required")
    source = Path(kit_path).expanduser().resolve()
    target = target_path.expanduser().resolve()
    if source == target:
        raise ValueError("Recovery kit must be different from the active vault")
    if source.is_symlink() or not source.is_file():
        raise FileNotFoundError("Recovery kit was not found")
    source_bytes = source.read_bytes()
    if expected_kit_sha256 is not None and hashlib.sha256(source_bytes).hexdigest() != expected_kit_sha256:
        raise ValueError("Recovery kit changed after the preview")
    payload = decrypt_payload(code, source_bytes)
    if not isinstance(payload, dict) or payload.get("version") != 2 or not isinstance(payload.get("entries"), dict):
        raise ValueError("Recovery kit has an unsupported payload")
    require_clean_storage(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / f".{target.name}.recovery-{secrets.token_hex(16)}.tmp"
    try:
        create_v3_file(temporary, new_password, payload)
        candidate = temporary.read_bytes()
        atomic_write_bytes(
            target,
            candidate,
            validator=lambda item: decrypt_payload(new_password, item),
            expected_old_sha256=expected_target_sha256 or None,
            must_not_exist=expected_target_sha256 == "",
        )
    finally:
        if temporary.exists():
            temporary.unlink()

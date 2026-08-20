from __future__ import annotations

import hashlib
import json
from pathlib import Path

from vault_unified.crypto import read_encrypted_file, write_encrypted_file
from vault_unified.storage import atomic_write_bytes, require_clean_storage
from vault_unified.sync.conflicts import ConflictRecord
from vault_unified.v3_crypto import V3Credential, V3DeviceCredential

CONFLICTS_FILENAME = "conflicts.vault"
MIGRATION_MARKER_SUFFIX = ".migrated.json"


def conflicts_path(vault_path: Path) -> Path:
    return vault_path.parent / CONFLICTS_FILENAME


def conflicts_migration_path(vault_path: Path) -> Path:
    return vault_path.parent / f"{CONFLICTS_FILENAME}{MIGRATION_MARKER_SUFFIX}"


def legacy_conflicts_migrated(vault_path: Path) -> bool:
    sidecar = conflicts_path(vault_path)
    marker = conflicts_migration_path(vault_path)
    if not sidecar.exists() or not marker.exists():
        return False
    try:
        value = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    return value == {
        "version": 1,
        "vault_file": Path(vault_path).name,
        "legacy_conflicts_sha256": hashlib.sha256(sidecar.read_bytes()).hexdigest(),
        "state": "embedded",
    }


def mark_legacy_conflicts_migrated(vault_path: Path) -> None:
    sidecar = conflicts_path(vault_path)
    if not sidecar.exists():
        return
    marker = conflicts_migration_path(vault_path)
    value = {
        "version": 1,
        "vault_file": Path(vault_path).name,
        "legacy_conflicts_sha256": hashlib.sha256(sidecar.read_bytes()).hexdigest(),
        "state": "embedded",
    }
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def validate(candidate: bytes) -> None:
        if json.loads(candidate.decode("utf-8")) != value:
            raise ValueError("Legacy conflict migration marker did not round-trip")

    atomic_write_bytes(marker, encoded, validator=validate)


def load_conflicts(
    vault_path: Path, credential: V3Credential
) -> dict[str, ConflictRecord]:
    path = conflicts_path(vault_path)
    require_clean_storage(path)
    if not path.exists():
        return {}
    if legacy_conflicts_migrated(vault_path):
        return {}
    if conflicts_migration_path(vault_path).exists():
        raise ValueError(
            "Legacy conflict migration marker does not match its preserved sidecar"
        )
    if isinstance(credential, V3DeviceCredential):
        raise ValueError(
            "Device unlock cannot open the legacy conflict sidecar; unlock with the password"
        )
    try:
        raw = read_encrypted_file(path, credential)
    except Exception as exc:
        raise ValueError(
            "Legacy conflict sidecar could not be authenticated; recovery is required"
        ) from exc
    items = raw.get("conflicts", [])
    if not isinstance(items, list):
        return {}
    out: dict[str, ConflictRecord] = {}
    for item in items:
        try:
            rec = ConflictRecord.from_dict(item)
            out[rec.id] = rec
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Legacy conflict sidecar contains an invalid record") from exc
    return out


def save_conflicts(
    vault_path: Path,
    credential: V3Credential,
    conflicts: dict[str, ConflictRecord],
) -> None:
    if isinstance(credential, V3DeviceCredential):
        raise ValueError(
            "Device unlock cannot persist the legacy conflict sidecar; unlock with the password"
        )
    path = conflicts_path(vault_path)
    payload = {
        "conflicts": [c.to_dict(reveal=True) for c in conflicts.values()],
    }
    write_encrypted_file(path, credential, payload)

from __future__ import annotations

from pathlib import Path

from vault_unified.crypto import read_encrypted_file, write_encrypted_file
from vault_unified.storage import require_clean_storage
from vault_unified.sync.conflicts import ConflictRecord
from vault_unified.v3_crypto import V3Credential, V3DeviceCredential

CONFLICTS_FILENAME = "conflicts.vault"


def conflicts_path(vault_path: Path) -> Path:
    return vault_path.parent / CONFLICTS_FILENAME


def load_conflicts(
    vault_path: Path, credential: V3Credential
) -> dict[str, ConflictRecord]:
    path = conflicts_path(vault_path)
    require_clean_storage(path)
    if not path.exists():
        return {}
    if isinstance(credential, V3DeviceCredential):
        raise ValueError(
            "Device unlock cannot open the legacy conflict sidecar; unlock with the password"
        )
    try:
        raw = read_encrypted_file(path, credential)
    except Exception:
        return {}
    items = raw.get("conflicts", [])
    if not isinstance(items, list):
        return {}
    out: dict[str, ConflictRecord] = {}
    for item in items:
        try:
            rec = ConflictRecord.from_dict(item)
            out[rec.id] = rec
        except (KeyError, TypeError, ValueError):
            continue
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

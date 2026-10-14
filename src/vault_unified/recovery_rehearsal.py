"""Exercise the real recovery writer in an isolated, encrypted temporary vault."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import secrets
from tempfile import TemporaryDirectory

from vault_unified.crypto import decrypt_payload
from vault_unified.local_store import LocalVault
from vault_unified.organization import organization_for
from vault_unified.personal_data import all_history, data_for
from vault_unified.recovery_kit import _validate_code, restore_from_recovery_kit
from vault_unified.vault_format import MAX_VAULT_BYTES


def rehearse_recovery(kit_path: str | Path, recovery_code: str) -> dict:
    code = _validate_code(recovery_code)
    source = Path(kit_path).expanduser()
    if source.is_symlink() or not source.is_file():
        raise ValueError("Choose an encrypted recovery file")
    with source.open("rb") as stream:
        encrypted = stream.read(MAX_VAULT_BYTES + 1)
    if len(encrypted) > MAX_VAULT_BYTES:
        raise ValueError("Recovery file is too large")
    original = decrypt_payload(code, encrypted)
    # Only ciphertext reaches disk. The active vault/config/session are never
    # passed to the recovery writer, even on a computer without an existing vault.
    with TemporaryDirectory(prefix="vault-recovery-rehearsal-") as directory:
        kit = Path(directory) / "source.vault"
        target = Path(directory) / "restored.vault"
        kit.write_bytes(encrypted)
        temporary_password = secrets.token_urlsafe(48)
        restore_from_recovery_kit(target, kit, code, temporary_password, expected_target_sha256="")
        restored = decrypt_payload(temporary_password, target.read_bytes())
        if restored != original:
            raise ValueError("Recovered data did not match the package")
        local = LocalVault(target, temporary_password)
        counts = dict(entries=0, active=0, archived=0, trash=0, attachments=0, history=0, totp=0)
        for entry in local.list_entries():
            personal = data_for(entry)
            counts["entries"] += 1
            counts[organization_for(entry)["state"]] += 1
            counts["attachments"] += len(personal["attachments"])
            counts["history"] += len(all_history(entry))
            counts["totp"] += bool(personal["totp_secret"])
        schema = local.payload_version
    return {"verified_at": datetime.now(timezone.utc).isoformat(), "payload_version": schema,
            "counts": counts, "complete_payload_matched": True, "temporary_copy_removed": True}

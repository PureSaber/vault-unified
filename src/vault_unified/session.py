from __future__ import annotations

import os
import hashlib
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from vault_unified.config import get_vault_path
from vault_unified.crypto import decrypt_payload
from vault_unified.device_keyring import (
    device_slot_metadata,
    enable_device_unlock,
    load_device_credential,
)
from vault_unified.keyring_store import get_master_password, save_master_password
from vault_unified.manager import UnifiedVault
from vault_unified.storage import atomic_write_bytes, require_clean_storage
from vault_unified.v3_crypto import create_v3_file
from vault_unified.vault_format import is_framed_vault_file

SESSION_IDLE_SECONDS = 30 * 60
EMPTY_VAULT_PAYLOAD = {"version": 2, "entries": {}}


@dataclass
class VaultSession:
    token: str
    vault: UnifiedVault
    last_active: float

    def touch(self) -> None:
        self.last_active = time.time()

    def expired(self) -> bool:
        return (time.time() - self.last_active) > SESSION_IDLE_SECONDS


class SessionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, VaultSession] = {}

    def _register(self, vault: UnifiedVault) -> tuple[str, UnifiedVault]:
        token = str(uuid4())
        self._sessions[token] = VaultSession(
            token=token,
            vault=vault,
            last_active=time.time(),
        )
        return token, vault

    @staticmethod
    def _remember(path: Path, password: str) -> None:
        if is_framed_vault_file(path):
            enable_device_unlock(path, password)
        else:
            save_master_password(password)

    def unlock(
        self,
        password: str | None = None,
        *,
        vault_path: Path | None = None,
        remember: bool = False,
    ) -> tuple[str, UnifiedVault]:
        path = vault_path or get_vault_path()
        require_clean_storage(path)
        if not path.exists():
            raise FileNotFoundError(
                "Vault does not exist; create a new vault or restore a backup first"
            )
        is_framed = is_framed_vault_file(path)
        pwd = password or os.environ.get("VAULT_PASSWORD")
        if not pwd and not is_framed:
            pwd = get_master_password()
        credential = pwd
        if not credential and is_framed:
            if device_slot_metadata(path) is None:
                raise ValueError("Master password required; device unlock is not enabled")
            credential = load_device_credential(path)
        if not credential:
            raise ValueError("Master password or enabled device unlock required")
        vault = UnifiedVault(path, credential)
        if remember:
            if not isinstance(credential, str):
                raise ValueError("Enter the master password before enabling device unlock")
            self._remember(path, credential)
        return self._register(vault)

    def create_v3(
        self,
        password: str,
        confirm_password: str,
        *,
        vault_path: Path | None = None,
        remember: bool = False,
    ) -> tuple[str, UnifiedVault]:
        if password != confirm_password:
            raise ValueError("Master password confirmation does not match")
        path = vault_path or get_vault_path()
        require_clean_storage(path)
        if path.exists():
            raise FileExistsError(f"Vault already exists: {path}")
        create_v3_file(path, password, EMPTY_VAULT_PAYLOAD)
        vault = UnifiedVault(path, password)
        if remember:
            self._remember(path, password)
        return self._register(vault)

    def restore(
        self,
        backup_path: str | Path,
        password: str,
        *,
        vault_path: Path | None = None,
        remember: bool = False,
        expected_source_sha256: str | None = None,
    ) -> tuple[str, UnifiedVault]:
        source = Path(backup_path).expanduser().resolve()
        target = (vault_path or get_vault_path()).expanduser().resolve()
        require_clean_storage(target)
        if target.exists():
            raise FileExistsError(f"Vault already exists: {target}")
        if source == target:
            raise ValueError("Backup path must be different from the active vault path")
        if not source.is_file():
            raise FileNotFoundError(f"Backup file not found: {source}")

        source_bytes = source.read_bytes()
        if (
            expected_source_sha256 is not None
            and hashlib.sha256(source_bytes).hexdigest() != expected_source_sha256
        ):
            raise ValueError("Backup changed after the restore preview")
        decrypt_payload(password, source_bytes)
        atomic_write_bytes(
            target,
            source_bytes,
            validator=lambda candidate: decrypt_payload(password, candidate),
            must_not_exist=True,
        )
        vault = UnifiedVault(target, password)
        if remember:
            self._remember(target, password)
        return self._register(vault)

    def get(self, token: str) -> UnifiedVault:
        session = self._sessions.get(token)
        if not session or session.expired():
            if session:
                del self._sessions[token]
            raise PermissionError("Session expired or invalid")
        session.touch()
        return session.vault

    def lock(self, token: str) -> None:
        self._sessions.pop(token, None)

    def lock_all(self) -> None:
        self._sessions.clear()

    def is_unlocked(self, token: str) -> bool:
        session = self._sessions.get(token)
        return session is not None and not session.expired()


sessions = SessionManager()

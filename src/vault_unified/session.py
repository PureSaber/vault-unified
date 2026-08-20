from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from vault_unified.config import get_vault_path
from vault_unified.device_keyring import (
    device_slot_metadata,
    enable_device_unlock,
    load_device_credential,
)
from vault_unified.keyring_store import get_master_password, save_master_password
from vault_unified.manager import UnifiedVault
from vault_unified.storage import require_clean_storage
from vault_unified.vault_format import is_framed_vault_file

SESSION_IDLE_SECONDS = 30 * 60


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

    def unlock(
        self,
        password: str | None = None,
        *,
        vault_path: Path | None = None,
        remember: bool = False,
    ) -> tuple[str, UnifiedVault]:
        path = vault_path or get_vault_path()
        require_clean_storage(path)
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
        if not path.exists():
            if not isinstance(credential, str):  # pragma: no cover - defensive guard
                raise ValueError("A password is required to create a vault")
            vault = UnifiedVault.create(path, credential)
        else:
            vault = UnifiedVault(path, credential)
        if remember and is_framed:
            if not isinstance(credential, str):
                raise ValueError("A password is required to enable device unlock")
            enable_device_unlock(path, credential)
        elif remember:
            if not isinstance(credential, str):  # pragma: no cover - legacy invariant
                raise ValueError("A password is required for legacy remember")
            save_master_password(credential)
        token = str(uuid4())
        self._sessions[token] = VaultSession(token=token, vault=vault, last_active=time.time())
        return token, vault

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

    def is_unlocked(self, token: str) -> bool:
        session = self._sessions.get(token)
        return session is not None and not session.expired()


sessions = SessionManager()

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from vault_unified.config import get_vault_path
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
        if remember and is_framed:
            raise ValueError(
                "Remembering a raw V3 password is disabled until reviewed device slots ship in 5e"
            )
        pwd = password or os.environ.get("VAULT_PASSWORD")
        if not pwd and not is_framed:
            pwd = get_master_password()
        if not pwd:
            raise ValueError("Master password required")
        if not path.exists():
            vault = UnifiedVault.create(path, pwd)
        else:
            vault = UnifiedVault(path, pwd)
        if remember:
            save_master_password(pwd)
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

from __future__ import annotations

import os
import hashlib
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4
from threading import RLock
from contextlib import contextmanager

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
from vault_unified.vault_format import V3Container, inspect_vault_format_file, is_framed_vault_file

SESSION_IDLE_SECONDS = 30 * 60
EMPTY_VAULT_PAYLOAD = {"version": 3, "entries": {}, "metadata": {}}


@dataclass
class VaultSession:
    token: str
    vault: UnifiedVault
    last_active: float
    browser_binding: tuple[str, str, str] | None = None
    master_verified: bool = False

    def touch(self) -> None:
        self.last_active = time.time()

    def expired(self) -> bool:
        return (time.time() - self.last_active) > SESSION_IDLE_SECONDS


class SessionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, VaultSession] = {}
        self._guard = RLock()
        self._epoch = 0
        self._system_epoch = 0
        self._system_blocked = False

    def begin_unlock(self) -> int:
        with self._guard:
            if self._system_blocked:
                raise PermissionError("Windows session is locked or suspended")
            return self._epoch

    @property
    def system_epoch(self) -> int:
        with self._guard:
            return self._system_epoch

    def set_system_blocked(self, blocked: bool) -> list[str]:
        with self._guard:
            self._system_blocked = blocked
            self._system_epoch += 1
            tokens = list(self._sessions)
            self.lock_all()
            return tokens

    def reset_renderer(self) -> list[str]:
        """Revoke a replaced desktop document without changing OS lock state."""
        with self._guard:
            self._system_epoch += 1
            tokens = list(self._sessions)
            self.lock_all()
            return tokens

    def _register(self, vault: UnifiedVault, *, expected_epoch: int, master_verified: bool = True) -> tuple[str, UnifiedVault]:
        from vault_unified.generation_history import prune
        prune(vault.local)
        token = str(uuid4())
        container = inspect_vault_format_file(vault.vault_path)
        binding = None
        if isinstance(container, V3Container):
            binding = (
                str(vault.vault_path.resolve()),
                container.header.vault_id,
                container.header.dek_id,
            )
        with self._guard:
            if self._system_blocked or expected_epoch != self._epoch:
                raise PermissionError("Unlock was cancelled by a lock event")
            self._sessions[token] = VaultSession(
                token=token,
                vault=vault,
                last_active=time.time(),
                browser_binding=binding,
                master_verified=master_verified,
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
        master_verified: bool = True,
        expected_epoch: int | None = None,
    ) -> tuple[str, UnifiedVault]:
        epoch = self.begin_unlock()
        if expected_epoch is not None and epoch != expected_epoch:
            raise PermissionError("Unlock was cancelled by a lock event")
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
        return self._register(vault, expected_epoch=epoch, master_verified=master_verified and bool(password))

    def create_v3(
        self,
        password: str,
        confirm_password: str,
        *,
        vault_path: Path | None = None,
        remember: bool = False,
    ) -> tuple[str, UnifiedVault]:
        epoch = self.begin_unlock()
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
        return self._register(vault, expected_epoch=epoch)

    def restore(
        self,
        backup_path: str | Path,
        password: str,
        *,
        vault_path: Path | None = None,
        remember: bool = False,
        expected_source_sha256: str | None = None,
    ) -> tuple[str, UnifiedVault]:
        epoch = self.begin_unlock()
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
        return self._register(vault, expected_epoch=epoch)

    def get(self, token: str, *, touch: bool = True) -> UnifiedVault:
        with self._guard:
            session = self._sessions.get(token)
            if not session or session.expired():
                if session:
                    del self._sessions[token]
                    from vault_unified.personal_sync.connections import connections
                    connections.clear_scope(token)
                    from vault_unified.passkey_requests import requests
                    requests.clear(token)
                    self._retain_connect_requests()
                raise PermissionError("Session expired or invalid")
            if touch:
                session.touch()
            return session.vault

    @contextmanager
    def active(self, token: str, vault):
        """Serialize a short local commit with explicit/system session locking."""
        with self._guard:
            if self.get(token, touch=False) is not vault:
                raise PermissionError("Desktop session changed")
            yield

    def browser_binding(self, token: str) -> tuple[str, str, str] | None:
        with self._guard:
            self.get(token, touch=False)
            return self._sessions[token].browser_binding

    def master_authenticated(self, token: str) -> bool:
        with self._guard:
            self.get(token, touch=False)
            return self._sessions[token].master_verified

    def browser_session(self, binding: tuple[str, str, str]) -> str:
        """Find an already-unlocked vault; never unlock or extend idle time."""
        for token, session in list(self._sessions.items()):
            if not session.expired() and session.browser_binding == binding:
                return token
        raise PermissionError("Desktop vault is locked")

    def lock(self, token: str) -> None:
        with self._guard:
            if self._sessions.pop(token, None):
                self._epoch += 1
            from vault_unified.personal_sync.connections import connections
            connections.clear_scope(token)
            from vault_unified.passkey_requests import requests
            requests.clear(token)
            self._retain_connect_requests()

    def lock_all(self) -> None:
        with self._guard:
            self._epoch += 1
            self._sessions.clear()
            from vault_unified.personal_sync.connections import connections
            connections.clear_scope(None)
            from vault_unified.passkey_requests import requests
            requests.clear()
            self._retain_connect_requests()

    def live_browser_bindings(self) -> set:
        """Bindings of unlocked sessions; `None` stands for a vault before v3."""
        with self._guard:
            return {session.browser_binding for session in self._sessions.values() if not session.expired()}

    def _retain_connect_requests(self) -> None:
        # Called with the guard held: session manager -> connect store, never the reverse.
        from vault_unified.browser_connect import browser_connects
        browser_connects.retain(self.live_browser_bindings())

    def is_unlocked(self, token: str) -> bool:
        session = self._sessions.get(token)
        return session is not None and not session.expired()


sessions = SessionManager()

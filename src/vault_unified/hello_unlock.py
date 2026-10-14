"""Process-only, encrypted quick-unlock material; the wrapping key comes from Hello."""
from __future__ import annotations

from dataclasses import dataclass
import hmac
import secrets
from threading import RLock

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from vault_unified.config import get_vault_path
from vault_unified.session import sessions


class HelloUnlockError(ValueError):
    pass


@dataclass(repr=False)
class SealedCredential:
    grant_id: str
    path: str
    nonce: bytes
    ciphertext: bytes


class HelloUnlockCache:
    def __init__(self):
        self._record: SealedCredential | None = None
        self._guard = RLock()

    def prepare(self, token: str, wrapping_key: bytes) -> str:
        vault = sessions.get(token)
        if len(wrapping_key) != 32 or not sessions.master_authenticated(token):
            raise HelloUnlockError("Unlock with the master password before enabling Windows Hello")
        credential = vault.local.credential
        if not isinstance(credential, str):
            raise HelloUnlockError("Master password unlock required")
        grant_id = secrets.token_hex(32)
        path = str(vault.vault_path.resolve())
        nonce = secrets.token_bytes(12)
        ciphertext = AESGCM(wrapping_key).encrypt(nonce, credential.encode("utf-8"), (grant_id + path).encode("utf-8"))
        with self._guard:
            # The credential may have been read before a concurrent Windows lock.
            sessions.get(token, touch=False)
            self._record = SealedCredential(grant_id, path, nonce, ciphertext)
        return grant_id

    def unlock(self, grant_id: str, wrapping_key: bytes) -> str:
        epoch = sessions.begin_unlock()
        with self._guard:
            record = self._record
        if (record is None or not hmac.compare_digest(grant_id, record.grant_id)
                or record.path != str(get_vault_path().resolve()) or len(wrapping_key) != 32):
            raise HelloUnlockError("Windows Hello needs a new master-password unlock")
        try:
            credential = AESGCM(wrapping_key).decrypt(record.nonce, record.ciphertext, (record.grant_id + record.path).encode("utf-8")).decode("utf-8")
            token, _ = sessions.unlock(credential, master_verified=False, expected_epoch=epoch)
            with self._guard:
                if self._record is not record:
                    sessions.lock(token)
                    raise HelloUnlockError("Windows Hello was disabled during unlock")
            return token
        except PermissionError:
            raise
        except Exception as exc:
            with self._guard:
                if self._record is record:
                    self._record = None
            raise HelloUnlockError("Windows Hello needs a new master-password unlock") from exc

    def clear(self):
        with self._guard:
            self._record = None


hello_unlock = HelloUnlockCache()

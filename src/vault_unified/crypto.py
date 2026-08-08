from __future__ import annotations

import json
import os
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

# Interactive local vault KDF (must stay stable — params are not stored in blob).
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SALT_BYTES = 16
NONCE_BYTES = 12
KEY_BYTES = 32


def derive_key(password: str, salt: bytes) -> bytes:
    kdf = Scrypt(
        salt=salt,
        length=KEY_BYTES,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
    )
    return kdf.derive(password.encode("utf-8"))


def encrypt_payload(password: str, payload: dict) -> bytes:
    salt = os.urandom(SALT_BYTES)
    nonce = os.urandom(NONCE_BYTES)
    key = derive_key(password, salt)
    plaintext = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, None)
    return salt + nonce + ciphertext


def decrypt_payload(password: str, blob: bytes) -> dict:
    if len(blob) < SALT_BYTES + NONCE_BYTES + 16:
        raise ValueError("Invalid vault file or corrupted data")
    salt = blob[:SALT_BYTES]
    nonce = blob[SALT_BYTES : SALT_BYTES + NONCE_BYTES]
    ciphertext = blob[SALT_BYTES + NONCE_BYTES :]
    key = derive_key(password, salt)
    plaintext = AESGCM(key).decrypt(nonce, ciphertext, None)
    return json.loads(plaintext.decode("utf-8"))


def write_encrypted_file(path: Path, password: str, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encrypt_payload(password, payload))


def read_encrypted_file(path: Path, password: str) -> dict:
    return decrypt_payload(password, path.read_bytes())


def mask_secret(value: str, visible: int = 0) -> str:
    if not value:
        return ""
    if visible <= 0:
        return "•" * min(len(value), 8)
    if len(value) <= visible:
        return "*" * len(value)
    return value[:visible] + "*" * (len(value) - visible)

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_VAULT_DIR = Path(os.environ.get("VAULT_DIR", ".vault"))
DEFAULT_VAULT_FILE = DEFAULT_VAULT_DIR / "secrets.vault"


def get_vault_path() -> Path:
    custom = os.environ.get("VAULT_FILE")
    if custom:
        return Path(custom)
    return DEFAULT_VAULT_FILE

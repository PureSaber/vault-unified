from __future__ import annotations

import os
import sys
from pathlib import Path


def _looks_like_repo_checkout(start: Path | None = None) -> bool:
    """True when running from a Vault Unified source checkout."""
    cur = (start or Path.cwd()).resolve()
    for candidate in [cur, *cur.parents]:
        pyproject = candidate / "pyproject.toml"
        pkg = candidate / "src" / "vault_unified"
        if pyproject.is_file() and pkg.is_dir():
            return True
        if (candidate / ".git").exists() and pyproject.is_file():
            return True
    return False


def get_data_dir() -> Path:
    """Writable app data root (repo cwd in checkout; LocalAppData when installed)."""
    custom = os.environ.get("VAULT_DATA_DIR")
    if custom:
        return Path(custom)

    if _looks_like_repo_checkout():
        return Path.cwd()

    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            return Path(local) / "VaultUnified"
        return Path.home() / "AppData" / "Local" / "VaultUnified"

    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / "VaultUnified"
    return Path.home() / ".local" / "share" / "VaultUnified"


def get_vault_dir() -> Path:
    custom = os.environ.get("VAULT_DIR")
    if custom:
        return Path(custom)
    return get_data_dir() / ".vault"


def get_vault_path() -> Path:
    custom = os.environ.get("VAULT_FILE")
    if custom:
        return Path(custom)
    return get_vault_dir() / "secrets.vault"


# Back-compat for callers that imported these names (lazy via properties would break).
DEFAULT_VAULT_DIR = Path(os.environ.get("VAULT_DIR", ".vault"))
DEFAULT_VAULT_FILE = DEFAULT_VAULT_DIR / "secrets.vault"

"""PyInstaller entry for the Vault Unified API sidecar."""

from __future__ import annotations

import os
from pathlib import Path


def prepare_data_dir() -> Path:
    """Use a writable data directory for installed / packaged runs.

    Prefer VAULT_DATA_DIR; otherwise LocalAppData\\VaultUnified on Windows.
    Sets VAULT_DIR / VAULT_FILE when unset so the vault is not relative to
    a non-writable install directory.
    """
    if os.environ.get("VAULT_DATA_DIR"):
        data = Path(os.environ["VAULT_DATA_DIR"])
    elif os.name == "nt":
        local = os.environ.get("LOCALAPPDATA")
        data = (
            Path(local) / "VaultUnified"
            if local
            else Path.home() / "AppData" / "Local" / "VaultUnified"
        )
    else:
        xdg = os.environ.get("XDG_DATA_HOME")
        data = (
            Path(xdg) / "VaultUnified"
            if xdg
            else Path.home() / ".local" / "share" / "VaultUnified"
        )

    data.mkdir(parents=True, exist_ok=True)
    os.chdir(data)
    os.environ.setdefault("VAULT_DATA_DIR", str(data))

    if "VAULT_FILE" not in os.environ and "VAULT_DIR" not in os.environ:
        vault_dir = data / ".vault"
        vault_dir.mkdir(parents=True, exist_ok=True)
        os.environ["VAULT_DIR"] = str(vault_dir)
        os.environ["VAULT_FILE"] = str(vault_dir / "secrets.vault")

    return data


prepare_data_dir()

from vault_unified.api.app import main  # noqa: E402

if __name__ == "__main__":
    main()

"""Public loopback discovery for Chrome/Edge's native messaging host.

The runtime file never contains authentication or decryption material. Browser
authorization remains an independent signed challenge against the unlocked vault.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

HOST_NAME = "org.vaultunified.desktop"
REGISTRY_BROWSERS = (r"Software\Google\Chrome\NativeMessagingHosts", r"Software\Microsoft\Edge\NativeMessagingHosts")
_ORIGIN = re.compile(r"^chrome-extension://[a-p]{32}$")


def discovery_dir() -> Path | None:
    value = os.environ.get("VAULT_BROWSER_DISCOVERY_DIR")
    return Path(value) if value else None


def _write_public(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError("Browser discovery path must be a regular file")
    # Disposable public configuration needs atomic replacement, not vault
    # recovery journals and ever-growing backup copies.
    fd, name = tempfile.mkstemp(prefix=".bridge-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, separators=(",", ":"))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def publish(port: int, instance_id: str) -> None:
    directory = discovery_dir()
    if directory is not None:
        _write_public(directory / "runtime.json", {
            "protocol": 1, "base_url": f"http://127.0.0.1:{port}/api", "instance_id": instance_id,
        })


def clear(instance_id: str) -> None:
    directory = discovery_dir()
    if directory is not None:
        path = directory / "runtime.json"
        try:
            if path.is_file() and path.stat().st_size <= 4096 and json.loads(path.read_text())["instance_id"] == instance_id:
                path.unlink()
        except (OSError, KeyError, ValueError):
            pass


def register(origin: str) -> bool:
    """Called only after a successful user-mediated pairing, never at import."""
    directory = discovery_dir()
    executable = os.environ.get("VAULT_BROWSER_HOST_EXE")
    if os.name != "nt" or directory is None or not executable:
        return False
    if not _ORIGIN.fullmatch(origin) or not Path(executable).is_file():
        return False
    import winreg

    path = directory / "native-host.json"
    allowed = {origin + "/"}
    try:
        if path.is_file() and path.stat().st_size <= 8192:
            old = json.loads(path.read_text(encoding="utf-8"))
            for item in old.get("allowed_origins", []):
                if isinstance(item, str) and item.endswith("/") and _ORIGIN.fullmatch(item[:-1]):
                    allowed.add(item)
        if len(allowed) > 32:
            return False
        _write_public(path, {"name": HOST_NAME, "description": "Discover the running Vault Unified desktop",
                            "path": str(Path(executable).resolve()), "type": "stdio", "allowed_origins": sorted(allowed)})
        for browser in REGISTRY_BROWSERS:
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, browser + "\\" + HOST_NAME, 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, "", 0, winreg.REG_SZ, str(path.resolve()))
        return True
    except (OSError, ValueError, TypeError):
        return False

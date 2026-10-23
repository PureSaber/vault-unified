"""Public loopback discovery for Chrome/Edge's native messaging host.

The runtime file never contains authentication or decryption material. Browser
authorization remains an independent signed challenge against the unlocked vault.
The separate owner-only connect file holds a per-run nonce that only allows
*asking* for a desktop-approved connection; the native host releases it to
allowlisted extensions, which keeps callers from other Windows accounts out.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import tempfile
from pathlib import Path

HOST_NAME = "org.vaultunified.desktop"
# The manifest `key` fixes the unpacked extension's ID; only its public half exists.
EXTENSION_ID = "llgobjolacibpkimbfgighcmblbnalpb"
EXTENSION_ORIGINS = frozenset({f"chrome-extension://{EXTENSION_ID}"})
CONNECT_FILE = "connect.json"
# Protected DACL granting the file owner full access and nobody else anything.
_OWNER_ONLY = "D:P(A;;FA;;;OW)"
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


def _write_private(path: Path, value: dict) -> None:
    """Create the file with an owner-only, non-inherited DACL from the start."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError("Browser discovery path must be a regular file")
    data = json.dumps(value, separators=(",", ":")).encode("utf-8")
    temporary = path.with_name(f".connect-{secrets.token_hex(8)}.tmp")
    if os.name != "nt":
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    else:
        import ctypes
        import msvcrt
        from ctypes import wintypes

        class SecurityAttributes(ctypes.Structure):
            _fields_ = [("nLength", wintypes.DWORD), ("lpSecurityDescriptor", wintypes.LPVOID),
                        ("bInheritHandle", wintypes.BOOL)]

        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(wintypes.LPVOID), ctypes.POINTER(wintypes.ULONG)]
        kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                         ctypes.POINTER(SecurityAttributes), wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel32.CreateFileW.restype = wintypes.HANDLE
        kernel32.LocalFree.argtypes = [wintypes.LPVOID]
        descriptor = wintypes.LPVOID()
        if not advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(_OWNER_ONLY, 1, ctypes.byref(descriptor), None):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            attributes = SecurityAttributes(ctypes.sizeof(SecurityAttributes), descriptor, False)
            # GENERIC_WRITE, no sharing, CREATE_NEW, FILE_ATTRIBUTE_NORMAL.
            handle = kernel32.CreateFileW(str(temporary), 0x40000000, 0, ctypes.byref(attributes), 1, 0x80, None)
            if handle in (None, wintypes.HANDLE(-1).value):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            kernel32.LocalFree(descriptor)
        fd = msvcrt.open_osfhandle(handle, os.O_WRONLY)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        # A same-volume rename keeps the file's own security descriptor.
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def publish(port: int, instance_id: str, connect_nonce: str = "") -> bool:
    """Publish discovery; return whether the connect nonce was stored privately."""
    directory = discovery_dir()
    if directory is None:
        return False
    _write_public(directory / "runtime.json", {
        "protocol": 1, "base_url": f"http://127.0.0.1:{port}/api", "instance_id": instance_id,
    })
    if not connect_nonce:
        return False
    try:
        _write_private(directory / CONNECT_FILE, {"instance_id": instance_id, "connect_nonce": connect_nonce})
        return True
    except (OSError, ValueError):
        return False


def clear(instance_id: str) -> None:
    directory = discovery_dir()
    if directory is not None:
        path = directory / "runtime.json"
        try:
            if path.is_file() and path.stat().st_size <= 4096 and json.loads(path.read_text())["instance_id"] == instance_id:
                path.unlink()
        except (OSError, KeyError, ValueError):
            pass
        path = directory / CONNECT_FILE
        try:
            if path.is_file() and path.stat().st_size <= 4096 and json.loads(path.read_text())["instance_id"] == instance_id:
                path.unlink()
        except (OSError, KeyError, ValueError):
            pass


def restore_registration() -> bool:
    """Restore an existing bridge after a manual upgrade/reinstall at the same path.

    The public manifest is retained with the local configuration. Restoring it
    cannot authorize a browser: signed device proof and vault unlock still apply.
    A new installation or a manifest owned by another executable is left alone.
    """
    directory = discovery_dir()
    executable = os.environ.get("VAULT_BROWSER_HOST_EXE")
    if os.name != "nt" or directory is None or not executable:
        return False
    path = directory / "native-host.json"
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 8192:
            return False
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("name") != HOST_NAME or value.get("type") != "stdio":
            return False
        previous = Path(value.get("path", ""))
        if not previous.is_absolute() or not previous.is_file() or previous.resolve() != Path(executable).resolve():
            return False
        origins = value.get("allowed_origins")
        if not isinstance(origins, list) or not 1 <= len(origins) <= 32:
            return False
        if not all(isinstance(origin, str) and origin.endswith("/") and _ORIGIN.fullmatch(origin[:-1]) for origin in origins):
            return False
        return register(origins[0][:-1])
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def _valid_origins(value) -> set[str]:
    return {item for item in value if isinstance(item, str) and item.endswith("/") and _ORIGIN.fullmatch(item[:-1])}         if isinstance(value, list) else set()


def _install(allowed: set[str]) -> bool:
    directory = discovery_dir()
    executable = os.environ.get("VAULT_BROWSER_HOST_EXE")
    if os.name != "nt" or directory is None or not executable or not Path(executable).is_file():
        return False
    if not 1 <= len(allowed) <= 32:
        return False
    import winreg

    path = directory / "native-host.json"
    try:
        _write_public(path, {"name": HOST_NAME, "description": "Discover the running Vault Unified desktop",
                            "path": str(Path(executable).resolve()), "type": "stdio", "allowed_origins": sorted(allowed)})
        for browser in REGISTRY_BROWSERS:
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, browser + "\\" + HOST_NAME, 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, "", 0, winreg.REG_SZ, str(path.resolve()))
        return True
    except (OSError, ValueError, TypeError):
        return False


def register(origin: str) -> bool:
    """Pairing enrolls an origin; startup may restore a previously owned manifest."""
    directory = discovery_dir()
    if os.name != "nt" or directory is None or not _ORIGIN.fullmatch(origin):
        return False
    path = directory / "native-host.json"
    allowed = {origin + "/"}
    try:
        if path.is_file() and path.stat().st_size <= 8192:
            allowed |= _valid_origins(json.loads(path.read_text(encoding="utf-8")).get("allowed_origins", []))
    except (OSError, ValueError, TypeError, AttributeError):
        return False
    return _install(allowed)


def register_fixed() -> bool:
    """Release-build start: let the fixed extension discover the desktop before any pairing.

    A manifest owned by another executable that still exists is left alone.
    Path-derived origins are kept only while a device record still uses them,
    so the fixed origin always fits within the 32-origin limit.
    """
    directory = discovery_dir()
    executable = os.environ.get("VAULT_BROWSER_HOST_EXE")
    if os.name != "nt" or directory is None or not executable or not Path(executable).is_file():
        return False
    path = directory / "native-host.json"
    previous_origins: set[str] = set()
    try:
        if path.is_symlink():
            return False
        if path.is_file():
            if path.stat().st_size > 8192:
                return False
            old = json.loads(path.read_text(encoding="utf-8"))
            previous = Path(old.get("path", ""))
            if previous.is_absolute() and previous.is_file() and previous.resolve() != Path(executable).resolve():
                return False
            previous_origins = _valid_origins(old.get("allowed_origins", []))
    except (OSError, ValueError, TypeError, AttributeError):
        return False
    from vault_unified.browser_trust import BrowserTrustError, browser_trust
    try:
        used = {origin + "/" for origin in browser_trust.origins()}
    except BrowserTrustError:
        used = previous_origins  # Unreadable device storage: keep what was registered.
    return _install({origin + "/" for origin in EXTENSION_ORIGINS} | (previous_origins & used))

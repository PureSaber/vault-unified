from __future__ import annotations

import ctypes
import platform
import subprocess
import threading


_clear_timer: threading.Timer | None = None
_clear_lock = threading.Lock()
CLIPBOARD_CLEAR_SECONDS = 45


def copy_to_clipboard(text: str, *, clear_after: int = CLIPBOARD_CLEAR_SECONDS) -> None:
    system = platform.system()
    if system == "Windows":
        subprocess.run(
            ["clip"],
            input=text.encode("utf-16le"),
            check=True,
        )
    elif system == "Darwin":
        subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)
    elif not _try_xclip(text):
        raise RuntimeError("Clipboard not supported on this platform")
    if clear_after > 0:
        _schedule_clear(clear_after, text)


def _schedule_clear(seconds: int, expected_text: str) -> None:
    global _clear_timer
    with _clear_lock:
        if _clear_timer is not None:
            _clear_timer.cancel()
        _clear_timer = threading.Timer(
            seconds,
            _clear_clipboard,
            args=(expected_text,),
        )
        _clear_timer.daemon = True
        _clear_timer.start()


def _clear_windows_clipboard_if_matches(expected_text: str) -> None:
    """Atomically clear CF_UNICODETEXT only when it is still our value."""
    from ctypes import wintypes

    cf_unicode_text = 13
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = wintypes.BOOL
    user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
    user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.GetClipboardData.restype = wintypes.HANDLE
    user32.EmptyClipboard.argtypes = []
    user32.EmptyClipboard.restype = wintypes.BOOL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL

    if not user32.OpenClipboard(None):
        return
    try:
        if not user32.IsClipboardFormatAvailable(cf_unicode_text):
            return
        handle = user32.GetClipboardData(cf_unicode_text)
        if not handle:
            return
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            return
        try:
            current = ctypes.wstring_at(pointer)
        finally:
            kernel32.GlobalUnlock(handle)
        if current == expected_text:
            user32.EmptyClipboard()
    finally:
        user32.CloseClipboard()


def _read_non_windows_clipboard(system: str) -> str | None:
    command = ["pbpaste"] if system == "Darwin" else [
        "xclip",
        "-selection",
        "clipboard",
        "-o",
    ]
    try:
        result = subprocess.run(command, capture_output=True, check=False)
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.decode("utf-8", errors="strict")


def _clear_clipboard(expected_text: str) -> None:
    try:
        system = platform.system()
        if system == "Windows":
            _clear_windows_clipboard_if_matches(expected_text)
            return
        current = _read_non_windows_clipboard(system)
        if current != expected_text:
            return
        if system == "Darwin":
            subprocess.run(["pbcopy"], input=b"", check=False)
        else:
            subprocess.run(
                ["xclip", "-selection", "clipboard"],
                input=b"",
                check=False,
            )
    except Exception:
        pass


def _try_xclip(text: str) -> bool:
    try:
        subprocess.run(
            ["xclip", "-selection", "clipboard"],
            input=text.encode("utf-8"),
            check=True,
        )
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False

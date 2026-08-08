from __future__ import annotations

import platform
import subprocess
import threading
import time


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
        _schedule_clear(clear_after)


def _schedule_clear(seconds: int) -> None:
    global _clear_timer
    with _clear_lock:
        if _clear_timer is not None:
            _clear_timer.cancel()
        _clear_timer = threading.Timer(seconds, _clear_clipboard)
        _clear_timer.daemon = True
        _clear_timer.start()


def _clear_clipboard() -> None:
    try:
        system = platform.system()
        if system == "Windows":
            subprocess.run(["clip"], input=b"\0", check=False)
        elif system == "Darwin":
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

from __future__ import annotations

import platform
import subprocess


def copy_to_clipboard(text: str) -> None:
    system = platform.system()
    if system == "Windows":
        subprocess.run(
            ["clip"],
            input=text.encode("utf-16le"),
            check=True,
        )
        return
    if system == "Darwin":
        subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)
        return
    if _try_xclip(text):
        return
    raise RuntimeError("Clipboard not supported on this platform")


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

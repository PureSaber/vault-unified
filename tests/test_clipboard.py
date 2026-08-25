from __future__ import annotations

import subprocess
from unittest.mock import Mock

from vault_unified import clipboard


def test_copy_schedules_clear_for_the_exact_copied_value(monkeypatch) -> None:
    run = Mock()
    schedule = Mock()
    monkeypatch.setattr(clipboard.platform, "system", lambda: "Windows")
    monkeypatch.setattr(clipboard.subprocess, "run", run)
    monkeypatch.setattr(clipboard, "_schedule_clear", schedule)

    clipboard.copy_to_clipboard("synthetic secret", clear_after=17)

    schedule.assert_called_once_with(17, "synthetic secret")


def test_windows_clear_uses_atomic_compare_and_clear(monkeypatch) -> None:
    clear_if_matches = Mock()
    monkeypatch.setattr(clipboard.platform, "system", lambda: "Windows")
    monkeypatch.setattr(
        clipboard,
        "_clear_windows_clipboard_if_matches",
        clear_if_matches,
    )

    clipboard._clear_clipboard("synthetic secret")

    clear_if_matches.assert_called_once_with("synthetic secret")


def test_changed_non_windows_clipboard_is_preserved(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout=b"new user content")

    monkeypatch.setattr(clipboard.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(clipboard.subprocess, "run", fake_run)

    clipboard._clear_clipboard("old copied password")

    assert calls == [["pbpaste"]]


def test_matching_non_windows_clipboard_is_cleared(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if command == ["pbpaste"]:
            return subprocess.CompletedProcess(command, 0, stdout=b"copied password")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(clipboard.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(clipboard.subprocess, "run", fake_run)

    clipboard._clear_clipboard("copied password")

    assert calls == [["pbpaste"], ["pbcopy"]]

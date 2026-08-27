from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from vault_unified.adapters.keepassxc import KeePassXCAdapter
from vault_unified.models import SecretEntry, Source


@pytest.fixture
def adapter(monkeypatch, tmp_path):
    db = tmp_path / "vault.kdbx"
    db.write_bytes(b"fake")
    monkeypatch.setenv("KEEPASSXC_DATABASE", str(db))
    monkeypatch.setenv("KEEPASSXC_PASSWORD", "dbpass")
    return KeePassXCAdapter()


def _completed(stdout: str = "", stderr: str = "", code: int = 0):
    return MagicMock(returncode=code, stdout=stdout, stderr=stderr)


def test_is_configured(adapter, monkeypatch):
    monkeypatch.setattr(
        "vault_unified.adapters.base.shutil.which",
        lambda name: "keepassxc-cli" if name == "keepassxc-cli" else None,
    )
    assert adapter.is_configured()


def test_is_available_checks_active_entry_paths(adapter, monkeypatch):
    monkeypatch.setattr(
        "vault_unified.adapters.base.shutil.which",
        lambda name: "keepassxc-cli" if name == "keepassxc-cli" else None,
    )
    with patch.object(adapter, "_list_entry_paths", return_value=[]) as list_paths:
        assert adapter.is_available()

    list_paths.assert_called_once_with()


def test_list_entries_parses_current_keepassxc_show_output(adapter, tmp_path):
    db = tmp_path / "vault.kdbx"
    ls_out = "Internet/\nInternet/GitHub\n"
    show_out = (
        "Title: GitHub\n"
        "UserName: user@example.com\n"
        "Password: secret123\n"
        "URL: https://github.com\n"
        "Notes: test note\n"
    )

    def fake_run(cmd, **kwargs):
        if "ls" in cmd:
            assert cmd == ["ls", "-R", "-f", str(db)]
            return _completed(ls_out)
        if "export" in cmd:
            return _completed("<KeePassFile><Meta /></KeePassFile>")
        if "show" in cmd:
            assert cmd == ["show", "-s", "--all", str(db), "Internet/GitHub"]
            return _completed(show_out)
        return _completed("", "fail", 1)

    with patch.object(adapter, "_run", side_effect=fake_run):
        entries = adapter.list_entries()

    assert len(entries) == 1
    assert entries[0].title == "GitHub"
    assert entries[0].username == "user@example.com"
    assert entries[0].password == "secret123"
    assert entries[0].external_id == "Internet/GitHub"
    assert entries[0].get_linked_id(Source.KEEPASSXC) == "Internet/GitHub"


def test_list_entries_prefixes_a_configured_group(adapter, monkeypatch, tmp_path):
    db = tmp_path / "vault.kdbx"
    monkeypatch.setenv("KEEPASSXC_GROUP", "Internet")

    def fake_run(cmd, **kwargs):
        if "ls" in cmd:
            assert cmd == ["ls", "-R", "-f", str(db), "Internet"]
            return _completed("GitHub\n")
        if "export" in cmd:
            return _completed("<KeePassFile><Meta /></KeePassFile>")
        if "show" in cmd:
            assert cmd == ["show", "-s", "--all", str(db), "Internet/GitHub"]
            return _completed("Title: GitHub\nUserName: user@example.com\n")
        return _completed("", "fail", 1)

    with patch.object(adapter, "_run", side_effect=fake_run):
        entries = adapter.list_entries()

    assert [entry.external_id for entry in entries] == ["Internet/GitHub"]


def test_create_entry(adapter, tmp_path):
    db = tmp_path / "vault.kdbx"

    def fake_run(cmd, **kwargs):
        assert kwargs.get("input_text") == "dbpass\nentrypass"
        assert "add" in cmd
        assert str(db) in cmd
        return _completed()

    entry = SecretEntry(title="GitHub", username="u", password="entrypass", source=Source.LOCAL)
    with patch.object(adapter, "_run", side_effect=fake_run):
        created = adapter.create_entry(entry)

    assert created.external_id == "GitHub"
    assert created.get_linked_id(Source.KEEPASSXC) == "GitHub"


def test_delete_entry_leaves_the_native_recycle_bin_recoverable(adapter, tmp_path):
    db = tmp_path / "vault.kdbx"
    with patch.object(adapter, "_run_db", return_value=_completed()) as run_db:
        adapter.delete_entry("Internet/GitHub")

    run_db.assert_called_once_with(["rm", str(db), "Internet/GitHub"])


def test_recycle_bin_entries_are_excluded_from_active_paths(adapter, tmp_path):
    db = tmp_path / "vault.kdbx"
    recycle_uuid = "recycle-bin-uuid"
    export = (
        "<KeePassFile><Meta><RecycleBinUUID>"
        f"{recycle_uuid}"
        "</RecycleBinUUID></Meta><Root><Group><UUID>root</UUID>"
        "<Name>Root</Name><Group><UUID>recycle-bin-uuid</UUID>"
        "<Name>回收站</Name></Group></Group></Root></KeePassFile>"
    )

    def fake_run(cmd, **kwargs):
        if "ls" in cmd:
            assert cmd == ["ls", "-R", "-f", str(db)]
            return _completed("Active\n回收站/\n回收站/Deleted\n")
        if "export" in cmd:
            return _completed(export)
        return _completed("", "fail", 1)

    with patch.object(adapter, "_run", side_effect=fake_run):
        assert adapter._list_entry_paths() == ["Active"]
        assert adapter.get_entry("Deleted") is None

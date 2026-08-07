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


def test_list_entries_parses_show(adapter):
    ls_out = "Internet/\nInternet/GitHub\n"
    show_out = (
        "Title: GitHub\n"
        "User: user@example.com\n"
        "Password: secret123\n"
        "URL: https://github.com\n"
        "Notes: test note\n"
    )

    def fake_run(cmd, **kwargs):
        if "ls" in cmd:
            return _completed(ls_out)
        if "show" in cmd:
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

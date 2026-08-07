from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from vault_unified.adapters.gopass import GopassAdapter
from vault_unified.models import SecretEntry, Source


@pytest.fixture
def adapter(monkeypatch):
    monkeypatch.setenv("GOPASS_PATH_PREFIX", "services")
    return GopassAdapter()


def _completed(stdout: str = "", stderr: str = "", code: int = 0):
    return MagicMock(returncode=code, stdout=stdout, stderr=stderr)


def test_entry_path_slug(adapter):
    entry = SecretEntry(title="Git Hub!", source=Source.LOCAL)
    assert adapter._entry_path(entry) == "services/git-hub"


def test_list_entries(adapter):
    ls_out = "services/github\nservices/other\n"
    show_github = "ghp_token\nusername: repo\nurl: https://github.com\n"

    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["ls", "--flat"]:
            return _completed(ls_out)
        if cmd[0] == "show" and cmd[1] == "services/github":
            return _completed(show_github)
        if cmd[0] == "show":
            return _completed("pw\n")
        return _completed("", "err", 1)

    with patch.object(adapter, "_run", side_effect=fake_run):
        entries = adapter.list_entries()

    assert len(entries) == 2
    gh = next(e for e in entries if e.external_id == "services/github")
    assert gh.password == "ghp_token"
    assert gh.username == "repo"
    assert gh.url == "https://github.com"


def test_create_entry_uses_insert_force(adapter):
    entry = SecretEntry(title="GitHub", username="u", password="p", source=Source.LOCAL)

    def fake_run(cmd, **kwargs):
        assert cmd[:3] == ["insert", "-f", "services/github"]
        body = kwargs.get("input_text", "")
        assert "p\n" in body
        assert "username: u" in body
        return _completed()

    with patch.object(adapter, "_run", side_effect=fake_run):
        created = adapter.create_entry(entry)

    assert created.external_id == "services/github"

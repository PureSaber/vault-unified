from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from vault_unified.local_store import LocalVault
from vault_unified.models import SecretEntry, Source, SyncPreferences, SyncStatus
from vault_unified.sync.conflicts import detect_conflict
from vault_unified.sync.engine import SyncEngine
from vault_unified.sync_prefs import save_prefs


@pytest.fixture
def vault_setup():
    with tempfile.TemporaryDirectory() as tmp:
        vault_path = Path(tmp) / "test.vault"
        local = LocalVault.create(vault_path, "testpass")
        vault = MagicMock()
        vault.local = local
        vault.vault_path = vault_path
        vault._last_errors = []
        engine = SyncEngine(vault)
        vault.sync = engine
        yield vault, engine, vault_path


def test_detect_conflict_dirty_without_remote_timestamp():
    local = SecretEntry(
        title="A",
        password="local",
        source=Source.LOCAL,
        sync_status=SyncStatus.DIRTY,
        last_synced_at="2020-01-01T00:00:00+00:00",
    )
    remote = SecretEntry(
        title="A",
        password="remote",
        source=Source.KEEPASSXC,
        external_id="A",
        remote_updated_at="",
    )
    assert detect_conflict(local, remote) is True


def test_pull_keepassxc_does_not_overwrite_dirty(vault_setup):
    vault, engine, vault_path = vault_setup
    save_prefs(vault_path, SyncPreferences(enabled_sources=["keepassxc"], conflict_default="manual"))
    local = SecretEntry(
        title="GitHub",
        password="local-secret",
        source=Source.KEEPASSXC,
        external_id="GitHub",
        sync_status=SyncStatus.DIRTY,
        last_synced_at="2020-01-01T00:00:00+00:00",
    )
    local.link_source(Source.KEEPASSXC, "GitHub")
    vault.local.add(local)

    remote = SecretEntry(
        title="GitHub",
        password="remote-secret",
        source=Source.KEEPASSXC,
        external_id="GitHub",
    )
    remote.link_source(Source.KEEPASSXC, "GitHub")

    adapter = MagicMock()
    adapter.is_configured.return_value = True
    adapter.is_available.return_value = True
    adapter.name = "KeePassXC"
    adapter.list_entries.return_value = [remote]

    with patch("vault_unified.sync.engine.get_adapter", return_value=adapter):
        stats = engine.pull_source(Source.KEEPASSXC)

    assert stats["conflicts"] == 1
    stored = vault.local.get(local.id)
    assert stored.password == "local-secret"
    assert stored.sync_status == SyncStatus.CONFLICT
    assert len(engine.list_conflicts()) == 1

    # Conflicts survive engine reload (disk persistence).
    engine2 = SyncEngine(vault)
    assert len(engine2.list_conflicts()) == 1
    assert engine2.list_conflicts()[0].remote.password == "remote-secret"


def test_push_delete_keeps_local_on_remote_failure(vault_setup):
    vault, engine, vault_path = vault_setup
    save_prefs(vault_path, SyncPreferences(enabled_sources=["bitwarden"]))
    entry = SecretEntry(
        title="X",
        password="p",
        source=Source.LOCAL,
        sync_status=SyncStatus.DELETED_PENDING,
    )
    entry.link_source(Source.BITWARDEN, "bw-1")
    vault.local.add(entry, mark_dirty=False)
    entry.sync_status = SyncStatus.DELETED_PENDING
    vault.local.replace_entry(entry)

    adapter = MagicMock()
    adapter.is_available.return_value = True
    adapter.delete_entry.side_effect = RuntimeError("fail")

    with patch("vault_unified.sync.engine.get_adapter", return_value=adapter):
        result = engine.push_entry(entry.id)

    assert result["errors"] == 1
    assert vault.local.get(entry.id) is not None
    assert vault.local.get(entry.id).sync_status == SyncStatus.DELETED_PENDING


def test_partial_push_keeps_dirty(vault_setup):
    vault, engine, vault_path = vault_setup
    save_prefs(
        vault_path,
        SyncPreferences(enabled_sources=["bitwarden", "keepassxc"]),
    )
    entry = SecretEntry(title="Y", password="p", source=Source.LOCAL, sync_status=SyncStatus.DIRTY)
    vault.local.add(entry)

    ok = MagicMock()
    ok.is_configured.return_value = True
    ok.is_available.return_value = True
    created: dict[str, SecretEntry] = {}

    def create_ok(e, *, operation_id=None):
        e.external_id = "bw-created"
        e.link_source(Source.BITWARDEN, "bw-created")
        created["entry"] = e
        return e

    ok.create_entry.side_effect = create_ok
    ok.get_entry.side_effect = lambda external_id: created.get("entry")

    fail = MagicMock()
    fail.is_configured.return_value = True
    fail.is_available.return_value = True
    fail.create_entry.side_effect = RuntimeError("nope")

    def pick(source):
        return ok if source == Source.BITWARDEN else fail

    with patch("vault_unified.sync.engine.get_adapter", side_effect=pick):
        result = engine.push_entry(entry.id)

    assert result["pushed"] == 1
    assert result["errors"] == 1
    assert vault.local.get(entry.id).sync_status == SyncStatus.DIRTY

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from vault_unified.local_store import LocalVault
from vault_unified.models import PrimarySource, SecretEntry, Source, SyncStatus
from vault_unified.adapters.registry import REMOTE_SOURCES, get_adapter
from vault_unified.sync.conflicts import apply_resolution, default_resolution, detect_conflict
from vault_unified.sync_prefs import load_prefs, save_prefs


@pytest.fixture
def vault_path():
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp) / "test.vault"


@pytest.fixture
def local_vault(vault_path):
    return LocalVault.create(vault_path, "testpass")


def test_create_and_list(local_vault):
    entry = SecretEntry(title="GitHub", username="user", password="secret")
    local_vault.add(entry)
    items = local_vault.list_entries()
    assert len(items) == 1
    assert items[0].title == "GitHub"
    assert items[0].sync_status == SyncStatus.DIRTY


def test_mark_dirty_on_update(local_vault):
    entry = SecretEntry(title="Test", password="a")
    local_vault.add(entry)
    local_vault.update(entry.id, password="b")
    updated = local_vault.get(entry.id)
    assert updated is not None
    assert updated.sync_status == SyncStatus.DIRTY


def test_vault_v1_migration(vault_path):
    from vault_unified.crypto import write_encrypted_file

    write_encrypted_file(
        vault_path,
        "testpass",
        {
            "version": 1,
            "entries": {
                "abc": {
                    "id": "abc",
                    "title": "Old",
                    "password": "x",
                    "source": "local",
                }
            },
        },
    )
    vault = LocalVault(vault_path, "testpass")
    entry = vault.get("abc")
    assert entry is not None
    assert entry.sync_status == SyncStatus.CLEAN


def test_detect_conflict():
    local = SecretEntry(
        title="A",
        password="local",
        sync_status=SyncStatus.DIRTY,
        last_synced_at="2020-01-01T00:00:00+00:00",
    )
    remote = SecretEntry(
        title="A",
        password="remote",
        remote_updated_at="2025-01-01T00:00:00+00:00",
    )
    assert detect_conflict(local, remote) is True


def test_default_resolution_primary_local():
    assert default_resolution(PrimarySource.LOCAL, Source.BITWARDEN) == "local"


def test_apply_resolution_local_wins():
    local = SecretEntry(title="A", password="local")
    remote = SecretEntry(title="A", password="remote")
    result = apply_resolution(local, remote, "local")
    assert result.password == "local"
    assert result.sync_status == SyncStatus.CLEAN


def test_sync_preferences_roundtrip(vault_path):
    from vault_unified.models import SyncPreferences

    prefs = SyncPreferences(primary=PrimarySource.BITWARDEN, auto_push_on_edit=False)
    save_prefs(vault_path, prefs)
    loaded = load_prefs(vault_path)
    assert loaded.primary == PrimarySource.BITWARDEN
    assert loaded.auto_push_on_edit is False


def test_remote_registry_includes_new_sources():
    assert Source.KEEPASSXC in REMOTE_SOURCES
    assert Source.GOPASS in REMOTE_SOURCES
    assert get_adapter(Source.KEEPASSXC).name == "KeePassXC"
    assert get_adapter(Source.GOPASS).name == "gopass"

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from vault_unified.adapters.registry import get_adapter
from vault_unified.local_store import LocalVault
from vault_unified.models import PrimarySource, SecretEntry, Source, SyncPreferences, SyncStatus
from vault_unified.sync.engine import SyncEngine


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


def test_default_enabled_sources_all_remote():
    prefs = SyncPreferences()
    enabled = prefs.get_enabled_sources()
    assert Source.BITWARDEN in enabled
    assert Source.KEEPASSXC in enabled
    assert Source.GOPASS in enabled
    assert Source.PROTON_PASS in enabled


def test_empty_enabled_sources_means_none_enabled():
    prefs = SyncPreferences(enabled_sources=[])
    assert prefs.get_enabled_sources() == []


def test_primary_reset_when_disabled():
    prefs = SyncPreferences(
        primary=PrimarySource.BITWARDEN,
        enabled_sources=["keepassxc"],
    )
    normalized = prefs.normalize()
    assert normalized.primary == PrimarySource.LOCAL


def test_pull_rejects_disabled_source(vault_setup):
    vault, engine, vault_path = vault_setup
    from vault_unified.sync_prefs import save_prefs

    save_prefs(
        vault_path,
        SyncPreferences(enabled_sources=["bitwarden"]),
    )
    with pytest.raises(RuntimeError, match="disabled"):
        engine.pull_source(Source.PROTON_PASS)


def test_push_only_enabled_sources(vault_setup):
    vault, engine, vault_path = vault_setup
    from vault_unified.sync_prefs import save_prefs

    save_prefs(
        vault_path,
        SyncPreferences(enabled_sources=["bitwarden"]),
    )
    entry = SecretEntry(title="Test", password="x", source=Source.LOCAL)
    vault.local.add(entry)

    bw = MagicMock()
    bw.is_configured.return_value = True
    bw.is_available.return_value = True
    bw.create_entry.return_value = entry

    proton = MagicMock()
    proton.is_configured.return_value = True
    proton.is_available.return_value = True

    def fake_get_adapter(source: Source):
        if source == Source.BITWARDEN:
            return bw
        if source == Source.PROTON_PASS:
            return proton
        return get_adapter(source)

    with patch("vault_unified.sync.engine.get_adapter", side_effect=fake_get_adapter):
        engine.push_entry(entry.id)

    bw.create_entry.assert_called_once()
    proton.create_entry.assert_not_called()

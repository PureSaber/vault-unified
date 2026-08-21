from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from vault_unified.cli import main
from vault_unified.adapters.bitwarden import BitwardenAdapter
from vault_unified.adapters.gopass import GopassAdapter
from vault_unified.adapters.keepassxc import KeePassXCAdapter
from vault_unified.adapters.proton_pass import ProtonPassAdapter
from vault_unified.crypto import read_encrypted_file
from vault_unified.local_store import LocalVault
from vault_unified.models import PrimarySource, SecretEntry, Source, SyncPreferences, SyncStatus
from vault_unified.sync.conflict_store import (
    conflicts_migration_path,
    conflicts_path,
    save_conflicts,
)
from vault_unified.sync.conflicts import ConflictRecord, new_conflict_id
from vault_unified.sync.engine import SyncEngine
from vault_unified.sync.ledger import (
    AdapterCapabilities,
    EntrySyncLedger,
    SyncLedgerError,
    Tombstone,
    content_fingerprint,
    entry_snapshot,
)
from vault_unified.sync_prefs import save_prefs


FAKE_PASSWORD = "generated-5f-vault-password"
LOCAL_SECRET = "generated-local-entry-secret"
REMOTE_SECRET = "generated-remote-entry-secret"


class FakeAdapter:
    def __init__(
        self,
        source: Source,
        *,
        capabilities: AdapterCapabilities | None = None,
    ) -> None:
        self.source = source
        self.name = f"fake-{source.value}"
        self.capabilities = capabilities or AdapterCapabilities(
            authoritative_list=True,
            revision_token=True,
            idempotent_create=False,
            delete_confirm=True,
            absence_is_delete=False,
        )
        self.entries: dict[str, SecretEntry] = {}
        self.operation_entries: dict[str, str] = {}
        self.create_operation_ids: list[str] = []
        self.update_operation_ids: list[str] = []
        self.delete_operation_ids: list[str] = []
        self.create_hook = None
        self.fail_after_create_write: Exception | None = None
        self.fail_get_count = 0
        self.available = True
        self.configured = True

    def is_available(self) -> bool:
        return self.available

    def is_configured(self) -> bool:
        return self.configured

    def list_entries(self) -> list[SecretEntry]:
        return [copy.deepcopy(entry) for entry in self.entries.values()]

    def get_entry(self, external_id: str) -> SecretEntry | None:
        if self.fail_get_count:
            self.fail_get_count -= 1
            raise RuntimeError(f"synthetic read failure {LOCAL_SECRET}")
        entry = self.entries.get(external_id)
        return copy.deepcopy(entry) if entry else None

    def create_entry(
        self, entry: SecretEntry, *, operation_id: str | None = None
    ) -> SecretEntry:
        assert operation_id is not None
        self.create_operation_ids.append(operation_id)
        if self.create_hook:
            self.create_hook(operation_id)
        existing_id = self.operation_entries.get(operation_id)
        if existing_id:
            return copy.deepcopy(self.entries[existing_id])
        external_id = f"{self.source.value}-{len(self.entries) + 1}"
        remote = copy.deepcopy(entry)
        remote.external_id = external_id
        remote.link_source(self.source, external_id)
        remote.remote_updated_at = f"revision-{len(self.entries) + 1}"
        self.entries[external_id] = remote
        self.operation_entries[operation_id] = external_id
        if self.fail_after_create_write:
            raise self.fail_after_create_write
        return copy.deepcopy(remote)

    def update_entry(
        self, entry: SecretEntry, *, operation_id: str | None = None
    ) -> SecretEntry:
        assert operation_id is not None
        self.update_operation_ids.append(operation_id)
        external_id = entry.get_linked_id(self.source) or entry.external_id
        if external_id not in self.entries:
            raise RuntimeError("synthetic missing remote")
        remote = copy.deepcopy(entry)
        remote.external_id = external_id
        remote.link_source(self.source, external_id)
        remote.remote_updated_at = f"revision-update-{len(self.update_operation_ids)}"
        self.entries[external_id] = remote
        return copy.deepcopy(remote)

    def delete_entry(
        self,
        external_id: str,
        *,
        permanent: bool = False,
        operation_id: str | None = None,
    ) -> None:
        assert operation_id is not None
        self.delete_operation_ids.append(operation_id)
        self.entries.pop(external_id, None)


@pytest.fixture
def vault_setup(tmp_path: Path):
    path = tmp_path / "synthetic-sync.vault"
    local = LocalVault.create(path, FAKE_PASSWORD)
    vault = MagicMock()
    vault.local = local
    vault.vault_path = path
    vault._last_errors = []
    save_prefs(
        path,
        SyncPreferences(
            enabled_sources=[Source.BITWARDEN.value],
            auto_push_on_edit=False,
        ),
    )
    engine = SyncEngine(vault)
    vault.sync = engine
    return vault, engine, path


def _remote(
    password: str = REMOTE_SECRET,
    *,
    external_id: str = "remote-1",
    revision: str = "revision-1",
) -> SecretEntry:
    entry = SecretEntry(
        title="Synthetic account",
        username="fake-user",
        password=password,
        source=Source.BITWARDEN,
        external_id=external_id,
        remote_updated_at=revision,
        sync_status=SyncStatus.CLEAN,
    )
    entry.link_source(Source.BITWARDEN, external_id)
    return entry


def _seed_pull(vault, engine, adapter: FakeAdapter) -> SecretEntry:
    adapter.entries["remote-1"] = _remote()
    with patch("vault_unified.sync.engine.get_adapter", return_value=adapter):
        stats = engine.pull_source(Source.BITWARDEN)
    assert stats["added"] == 1
    return vault.local.list_entries()[0]


def test_legacy_entry_fields_remain_readable_and_gain_bounded_ledger() -> None:
    legacy = {
        "id": "11111111-1111-4111-8111-111111111111",
        "title": "Legacy synthetic",
        "password": LOCAL_SECRET,
        "source": "local",
        "sync_status": "dirty",
    }
    entry = SecretEntry.from_dict(legacy)
    encoded = entry.to_dict()

    assert entry.password == LOCAL_SECRET
    assert encoded["title"] == legacy["title"]
    assert encoded["sync_ledger"]["version"] == 1
    assert encoded["sync_ledger"]["content_revision"]


def test_production_adapter_capabilities_are_explicit_and_conservative() -> None:
    expected = {
        BitwardenAdapter: (True, True, False, True, False),
        ProtonPassAdapter: (True, True, False, False, False),
        KeePassXCAdapter: (True, False, False, True, False),
        GopassAdapter: (True, False, False, True, False),
    }
    for adapter_type, values in expected.items():
        capabilities = adapter_type.capabilities
        assert (
            capabilities.authoritative_list,
            capabilities.revision_token,
            capabilities.idempotent_create,
            capabilities.delete_confirm,
            capabilities.absence_is_delete,
        ) == values


def test_ledger_tamper_and_fingerprint_mismatch_fail_closed() -> None:
    entry = SecretEntry(title="Synthetic", password=LOCAL_SECRET)
    replica = entry.sync_ledger.replica(
        Source.BITWARDEN.value,
        "remote-1",
        AdapterCapabilities(revision_token=True),
    )
    replica.record_base(
        entry,
        remote_revision="revision-1",
        local_revision=entry.sync_ledger.content_revision,
    )
    encoded = entry.to_dict()
    encoded["sync_ledger"]["replicas"][Source.BITWARDEN.value][
        "base_fingerprint"
    ] = "0" * 64

    with pytest.raises(SyncLedgerError, match="does not match"):
        SecretEntry.from_dict(encoded)

    encoded = entry.to_dict()
    encoded["sync_ledger"]["version"] = 99
    with pytest.raises(SyncLedgerError, match="unsupported"):
        SecretEntry.from_dict(encoded)


def test_three_way_pull_auto_advances_one_side_and_conflicts_concurrent(
    vault_setup,
) -> None:
    vault, engine, path = vault_setup
    save_prefs(
        path,
        SyncPreferences(
            primary=PrimarySource.BITWARDEN,
            enabled_sources=[Source.BITWARDEN.value],
            conflict_default="primary",
            auto_push_on_edit=False,
        ),
    )
    adapter = FakeAdapter(Source.BITWARDEN)
    local = _seed_pull(vault, engine, adapter)

    vault.local.update(local.id, password=LOCAL_SECRET)
    with patch("vault_unified.sync.engine.get_adapter", return_value=adapter):
        local_only = engine.pull_source(Source.BITWARDEN)
    assert local_only["conflicts"] == 0
    assert vault.local.get(local.id).password == LOCAL_SECRET

    adapter.entries["remote-1"].password = "generated-concurrent-remote"
    adapter.entries["remote-1"].remote_updated_at = "revision-2"
    with patch("vault_unified.sync.engine.get_adapter", return_value=adapter):
        concurrent = engine.pull_source(Source.BITWARDEN)

    assert concurrent["conflicts"] == 1
    assert vault.local.get(local.id).password == LOCAL_SECRET
    conflict = engine.list_conflicts()[0]
    assert conflict.default_choice == "remote"
    assert conflict.base_snapshot is not None
    assert conflict.remote.password == "generated-concurrent-remote"


def test_remote_only_change_advances_and_missing_revision_uses_fingerprint(
    vault_setup,
) -> None:
    vault, engine, _ = vault_setup
    adapter = FakeAdapter(
        Source.BITWARDEN,
        capabilities=AdapterCapabilities(
            authoritative_list=True,
            revision_token=False,
        ),
    )
    local = _seed_pull(vault, engine, adapter)
    adapter.entries["remote-1"].password = "generated-remote-only"
    adapter.entries["remote-1"].remote_updated_at = ""

    with patch("vault_unified.sync.engine.get_adapter", return_value=adapter):
        stats = engine.pull_source(Source.BITWARDEN)

    stored = vault.local.get(local.id)
    assert stats["updated"] == 1
    assert stored.password == "generated-remote-only"
    assert stored.sync_status == SyncStatus.CLEAN
    assert stored.sync_ledger.replicas[Source.BITWARDEN.value].remote_revision == ""


def test_noop_pull_does_not_rewrite_encrypted_vault(vault_setup) -> None:
    vault, engine, path = vault_setup
    adapter = FakeAdapter(Source.BITWARDEN)
    _seed_pull(vault, engine, adapter)
    before = path.read_bytes()

    with patch("vault_unified.sync.engine.get_adapter", return_value=adapter):
        stats = engine.pull_source(Source.BITWARDEN)

    assert stats["updated"] == 0
    assert stats["conflicts"] == 0
    assert path.read_bytes() == before


def test_multi_source_acknowledgements_are_independent(vault_setup) -> None:
    vault, engine, path = vault_setup
    save_prefs(
        path,
        SyncPreferences(
            enabled_sources=[Source.BITWARDEN.value, Source.KEEPASSXC.value],
            auto_push_on_edit=False,
        ),
    )
    entry = SecretEntry(title="Synthetic", password=LOCAL_SECRET)
    vault.local.add(entry)
    bitwarden = FakeAdapter(Source.BITWARDEN)
    keepass = FakeAdapter(Source.KEEPASSXC)

    def adapter_for(source: Source):
        return bitwarden if source == Source.BITWARDEN else keepass

    with patch("vault_unified.sync.engine.get_adapter", side_effect=adapter_for):
        assert engine.push_entry(entry.id)["pushed"] == 2
    first_revision = entry.sync_ledger.content_revision
    assert all(
        replica.last_acked_local_revision == first_revision
        for replica in entry.sync_ledger.replicas.values()
    )

    vault.local.update(entry.id, notes="synthetic local edit")
    with patch("vault_unified.sync.engine.get_adapter", side_effect=adapter_for):
        assert engine.push_entry(entry.id, [Source.BITWARDEN])["pushed"] == 1

    stored = vault.local.get(entry.id)
    assert (
        stored.sync_ledger.replicas[Source.BITWARDEN.value].last_acked_local_revision
        == stored.sync_ledger.content_revision
    )
    assert (
        stored.sync_ledger.replicas[Source.KEEPASSXC.value].last_acked_local_revision
        == first_revision
    )
    assert stored.sync_status == SyncStatus.DIRTY


def test_remote_conflict_choice_only_acknowledges_the_selected_replica(
    vault_setup,
) -> None:
    vault, engine, path = vault_setup
    save_prefs(
        path,
        SyncPreferences(
            enabled_sources=[Source.BITWARDEN.value, Source.KEEPASSXC.value],
            auto_push_on_edit=False,
        ),
    )
    entry = SecretEntry(title="Synthetic", password=LOCAL_SECRET)
    vault.local.add(entry)
    bitwarden = FakeAdapter(Source.BITWARDEN)
    keepass = FakeAdapter(Source.KEEPASSXC)

    def adapter_for(source: Source):
        return bitwarden if source == Source.BITWARDEN else keepass

    with patch("vault_unified.sync.engine.get_adapter", side_effect=adapter_for):
        assert engine.push_entry(entry.id)["pushed"] == 2
    old_revision = entry.sync_ledger.content_revision
    vault.local.update(entry.id, notes="synthetic local edit")
    remote_id = entry.get_linked_id(Source.BITWARDEN)
    bitwarden.entries[remote_id].notes = "synthetic remote winner"
    bitwarden.entries[remote_id].remote_updated_at = "revision-remote-winner"

    with patch("vault_unified.sync.engine.get_adapter", side_effect=adapter_for):
        assert engine.pull_source(Source.BITWARDEN)["conflicts"] == 1
        conflict = engine.list_conflicts()[0]
        resolved = engine.resolve_conflict(conflict.id, "remote")

    selected = resolved.sync_ledger.replicas[Source.BITWARDEN.value]
    remaining = resolved.sync_ledger.replicas[Source.KEEPASSXC.value]
    assert resolved.notes == "synthetic remote winner"
    assert selected.last_acked_local_revision == resolved.sync_ledger.content_revision
    assert remaining.last_acked_local_revision == old_revision
    assert resolved.sync_status == SyncStatus.DIRTY


def test_partial_or_non_deleting_listing_never_becomes_deletion(vault_setup) -> None:
    vault, engine, _ = vault_setup
    adapter = FakeAdapter(
        Source.BITWARDEN,
        capabilities=AdapterCapabilities(
            authoritative_list=True,
            revision_token=True,
            delete_confirm=True,
            absence_is_delete=False,
        ),
    )
    local = _seed_pull(vault, engine, adapter)
    adapter.entries.clear()

    with patch("vault_unified.sync.engine.get_adapter", return_value=adapter):
        stats = engine.pull_source(Source.BITWARDEN)

    stored = vault.local.get(local.id)
    assert stats["deleted_observed"] == 0
    assert stored.sync_ledger.tombstone is None
    assert (
        stored.sync_ledger.replicas[Source.BITWARDEN.value].absence_state
        == "unknown"
    )


def test_authoritative_documented_absence_creates_retained_tombstone(
    vault_setup,
) -> None:
    vault, engine, _ = vault_setup
    adapter = FakeAdapter(
        Source.BITWARDEN,
        capabilities=AdapterCapabilities(
            authoritative_list=True,
            revision_token=True,
            delete_confirm=True,
            absence_is_delete=True,
        ),
    )
    local = _seed_pull(vault, engine, adapter)
    adapter.entries.clear()

    with patch("vault_unified.sync.engine.get_adapter", return_value=adapter):
        stats = engine.pull_source(Source.BITWARDEN)

    stored = vault.local.get(local.id)
    assert stats["deleted_observed"] == 1
    assert stored.sync_status == SyncStatus.DELETED_PENDING
    assert stored.sync_ledger.tombstone is not None
    assert stored.sync_ledger.tombstone.acknowledged == [Source.BITWARDEN.value]
    assert vault.local.get(local.id) is not None


def test_concurrent_local_edit_and_remote_delete_requires_resolution(
    vault_setup,
) -> None:
    vault, engine, _ = vault_setup
    adapter = FakeAdapter(
        Source.BITWARDEN,
        capabilities=AdapterCapabilities(
            authoritative_list=True,
            revision_token=True,
            delete_confirm=True,
            absence_is_delete=True,
        ),
    )
    local = _seed_pull(vault, engine, adapter)
    vault.local.update(local.id, notes="synthetic unsynced note")
    adapter.entries.clear()

    with patch("vault_unified.sync.engine.get_adapter", return_value=adapter):
        stats = engine.pull_source(Source.BITWARDEN)

    stored = vault.local.get(local.id)
    assert stats["deleted_observed"] == 0
    assert stats["conflicts"] == 1
    assert stored.sync_ledger.tombstone is None
    conflict = engine.list_conflicts()[0]
    assert conflict.remote_deleted is True
    assert conflict.local.notes == "synthetic unsynced note"

    resolved = engine.resolve_conflict(conflict.id, "remote")
    assert resolved.sync_ledger.tombstone is not None
    assert resolved.sync_ledger.tombstone.acknowledged == [Source.BITWARDEN.value]


def test_remote_delete_local_resolution_recreates_instead_of_updating(
    vault_setup,
) -> None:
    vault, engine, _ = vault_setup
    adapter = FakeAdapter(
        Source.BITWARDEN,
        capabilities=AdapterCapabilities(
            authoritative_list=True,
            revision_token=True,
            delete_confirm=True,
            absence_is_delete=True,
        ),
    )
    local = _seed_pull(vault, engine, adapter)
    vault.local.update(local.id, notes="synthetic local winner")
    adapter.entries.clear()

    with patch("vault_unified.sync.engine.get_adapter", return_value=adapter):
        engine.pull_source(Source.BITWARDEN)
        conflict = engine.list_conflicts()[0]
        resolved = engine.resolve_conflict(conflict.id, "local")

    assert adapter.update_operation_ids == []
    assert len(adapter.create_operation_ids) == 1
    assert resolved.notes == "synthetic local winner"
    assert resolved.get_linked_id(Source.BITWARDEN) in adapter.entries
    assert resolved.sync_ledger.tombstone is None


def test_local_delete_persists_tombstone_before_remote_call_and_never_auto_purges(
    vault_setup,
) -> None:
    vault, engine, path = vault_setup
    adapter = FakeAdapter(Source.BITWARDEN)
    local = _seed_pull(vault, engine, adapter)
    observed: dict[str, bool] = {}

    def observe_delete(external_id, *, permanent=False, operation_id=None):
        persisted = LocalVault(path, FAKE_PASSWORD).get(local.id)
        observed["tombstone"] = persisted.sync_ledger.tombstone is not None
        adapter.entries.pop(external_id, None)

    adapter.delete_entry = observe_delete
    vault.local.delete(local.id, soft=True)

    soft_deleted = vault.local.get(local.id)
    persisted = LocalVault(path, FAKE_PASSWORD)
    assert soft_deleted is not None
    assert soft_deleted.sync_status == SyncStatus.DELETED_PENDING
    assert vault.local.list_entries() == []
    assert persisted.get(local.id).sync_status == SyncStatus.DELETED_PENDING
    assert persisted.list_entries() == []

    with patch("vault_unified.sync.engine.get_adapter", return_value=adapter):
        result = engine.push_entry(local.id)

    stored = vault.local.get(local.id)
    assert result == {"pushed": 1, "errors": 0}
    assert observed == {"tombstone": True}
    assert stored is not None
    assert stored.sync_ledger.tombstone.pending_sources() == []
    with pytest.raises(ValueError, match="retention"):
        engine.purge_tombstone(local.id)


def test_disabled_replica_stays_pending_until_explicit_abandon_and_retention(
    vault_setup,
) -> None:
    vault, engine, _ = vault_setup
    entry = SecretEntry(title="Synthetic", password=LOCAL_SECRET)
    entry.link_source(Source.BITWARDEN, "bw-1")
    entry.link_source(Source.KEEPASSXC, "kp-1")
    entry.sync_ledger.tombstone = Tombstone.create(
        [Source.BITWARDEN.value, Source.KEEPASSXC.value]
    )
    entry.sync_ledger.tombstone.acknowledged.append(Source.BITWARDEN.value)
    entry.sync_status = SyncStatus.DELETED_PENDING
    vault.local.add(entry, mark_dirty=False)

    assert entry.sync_ledger.tombstone.pending_sources() == [Source.KEEPASSXC.value]
    engine.abandon_tombstone_source(entry.id, Source.KEEPASSXC)
    future = datetime.now(timezone.utc) + timedelta(days=31)
    engine.purge_tombstone(entry.id, now=future)
    assert vault.local.get(entry.id) is None


def test_non_idempotent_crash_after_create_blocks_duplicate_retry(vault_setup) -> None:
    vault, engine, _ = vault_setup
    entry = SecretEntry(title="Synthetic", password=LOCAL_SECRET)
    vault.local.add(entry)
    adapter = FakeAdapter(Source.BITWARDEN)
    adapter.fail_after_create_write = RuntimeError(f"after write {LOCAL_SECRET}")

    with patch("vault_unified.sync.engine.get_adapter", return_value=adapter):
        first = engine.push_entry(entry.id)
        second = engine.push_entry(entry.id)

    assert first["errors"] == 1
    assert second["errors"] == 1
    assert len(adapter.entries) == 1
    assert len(adapter.create_operation_ids) == 1
    assert all(LOCAL_SECRET not in message for message in vault._last_errors)


def test_idempotent_create_reuses_operation_id_after_unknown_outcome(
    vault_setup,
) -> None:
    vault, engine, _ = vault_setup
    entry = SecretEntry(title="Synthetic", password=LOCAL_SECRET)
    vault.local.add(entry)
    adapter = FakeAdapter(
        Source.BITWARDEN,
        capabilities=AdapterCapabilities(
            authoritative_list=True,
            revision_token=True,
            idempotent_create=True,
            delete_confirm=True,
        ),
    )
    adapter.fail_after_create_write = RuntimeError("synthetic post-write crash")

    with patch("vault_unified.sync.engine.get_adapter", return_value=adapter):
        assert engine.push_entry(entry.id)["errors"] == 1
        adapter.fail_after_create_write = None
        assert engine.push_entry(entry.id) == {"pushed": 1, "errors": 0}

    assert len(adapter.entries) == 1
    assert len(set(adapter.create_operation_ids)) == 1


def test_create_readback_failure_reconciles_without_second_create(vault_setup) -> None:
    vault, engine, _ = vault_setup
    entry = SecretEntry(title="Synthetic", password=LOCAL_SECRET)
    vault.local.add(entry)
    adapter = FakeAdapter(Source.BITWARDEN)
    adapter.fail_get_count = 1

    with patch("vault_unified.sync.engine.get_adapter", return_value=adapter):
        assert engine.push_entry(entry.id)["errors"] == 1
        assert engine.push_entry(entry.id) == {"pushed": 1, "errors": 0}

    assert len(adapter.entries) == 1
    assert len(adapter.create_operation_ids) == 1


def test_conflict_snapshot_is_embedded_encrypted_and_legacy_sidecar_is_preserved(
    vault_setup,
) -> None:
    vault, engine, path = vault_setup
    adapter = FakeAdapter(Source.BITWARDEN)
    local = _seed_pull(vault, engine, adapter)
    vault.local.update(local.id, password=LOCAL_SECRET)
    conflict_secret = "generated-conflict-remote-secret"
    adapter.entries["remote-1"].password = conflict_secret
    adapter.entries["remote-1"].remote_updated_at = "revision-2"
    with patch("vault_unified.sync.engine.get_adapter", return_value=adapter):
        engine.pull_source(Source.BITWARDEN)

    assert not conflicts_path(path).exists()
    assert conflict_secret.encode() not in path.read_bytes()
    payload = read_encrypted_file(path, FAKE_PASSWORD)
    stored = next(iter(payload["entries"].values()))
    assert stored["sync_ledger"]["conflicts"]

    legacy_record = ConflictRecord(
        id=new_conflict_id(),
        entry_id=local.id,
        title=local.title,
        local=copy.deepcopy(local),
        remote=_remote("generated-legacy-remote"),
        remote_source=Source.BITWARDEN,
    )
    save_conflicts(path, FAKE_PASSWORD, {legacy_record.id: legacy_record})
    sidecar_before = conflicts_path(path).read_bytes()
    for entry in vault.local.list_entries(include_deleted=True):
        entry.sync_ledger.conflicts.clear()
    vault.local._save()

    migrated = SyncEngine(vault)
    assert migrated.list_conflicts()
    assert conflicts_path(path).read_bytes() == sidecar_before
    assert conflicts_migration_path(path).exists()

    conflicts_path(path).write_bytes(sidecar_before + b"synthetic-tamper")
    with pytest.raises(ValueError, match="marker does not match"):
        SyncEngine(vault)


def test_public_conflict_rendering_masks_every_snapshot_secret(vault_setup) -> None:
    vault, engine, _ = vault_setup
    adapter = FakeAdapter(Source.BITWARDEN)
    local = _seed_pull(vault, engine, adapter)
    vault.local.update(local.id, password=LOCAL_SECRET, notes=LOCAL_SECRET)
    public_remote_secret = "generated-public-remote-secret"
    adapter.entries["remote-1"].password = public_remote_secret
    adapter.entries["remote-1"].notes = public_remote_secret
    with patch("vault_unified.sync.engine.get_adapter", return_value=adapter):
        engine.pull_source(Source.BITWARDEN)

    public = engine.list_conflicts()[0].to_dict()
    rendered = json.dumps(public)
    assert LOCAL_SECRET not in rendered
    assert public_remote_secret not in rendered
    assert "sync_ledger" not in rendered


def test_operation_intent_is_durable_before_adapter_receives_plaintext(vault_setup) -> None:
    vault, engine, path = vault_setup
    entry = SecretEntry(title="Synthetic", password=LOCAL_SECRET)
    vault.local.add(entry)
    adapter = FakeAdapter(Source.BITWARDEN)

    def inspect_intent(operation_id: str) -> None:
        persisted = LocalVault(path, FAKE_PASSWORD).get(entry.id)
        pending = persisted.sync_ledger.replicas[Source.BITWARDEN.value].pending
        assert pending is not None
        assert pending.operation_id == operation_id
        assert pending.state == "intent"
        assert LOCAL_SECRET not in pending.to_dict().values()

    adapter.create_hook = inspect_intent
    with patch("vault_unified.sync.engine.get_adapter", return_value=adapter):
        assert engine.push_entry(entry.id) == {"pushed": 1, "errors": 0}


def test_content_fingerprint_is_deterministic_and_secret_sensitive() -> None:
    entry = SecretEntry(title="Synthetic", password=LOCAL_SECRET, tags=["b", "a"])
    snapshot = entry_snapshot(entry)
    assert content_fingerprint(entry) == content_fingerprint(snapshot)
    changed = dict(snapshot)
    changed["password"] = REMOTE_SECRET
    assert content_fingerprint(changed) != content_fingerprint(snapshot)


def test_empty_ledger_parser_rejects_unknown_conflict_shape() -> None:
    ledger = EntrySyncLedger().to_dict()
    ledger["conflicts"]["not-a-uuid"] = {"password": LOCAL_SECRET}
    with pytest.raises(SyncLedgerError, match="conflict ID"):
        EntrySyncLedger.from_dict(ledger)


def test_cli_tombstone_abandon_requires_explicit_confirmation(tmp_path: Path) -> None:
    path = tmp_path / "synthetic-cli-tombstone.vault"
    local = LocalVault.create(path, FAKE_PASSWORD)
    entry = SecretEntry(title="Synthetic tombstone", password=LOCAL_SECRET)
    entry.link_source(Source.KEEPASSXC, "kp-1")
    entry.sync_ledger.tombstone = Tombstone.create([Source.KEEPASSXC.value])
    entry.sync_status = SyncStatus.DELETED_PENDING
    local.add(entry, mark_dirty=False)
    runner = CliRunner()

    listed = runner.invoke(
        main,
        [
            "tombstones",
            "list",
            "--vault-path",
            str(path),
            "--password",
            FAKE_PASSWORD,
        ],
    )
    refused = runner.invoke(
        main,
        [
            "tombstones",
            "abandon",
            entry.id,
            "--source",
            Source.KEEPASSXC.value,
            "--vault-path",
            str(path),
            "--password",
            FAKE_PASSWORD,
        ],
    )
    abandoned = runner.invoke(
        main,
        [
            "tombstones",
            "abandon",
            entry.id,
            "--source",
            Source.KEEPASSXC.value,
            "--confirm-abandon",
            "--vault-path",
            str(path),
            "--password",
            FAKE_PASSWORD,
        ],
    )

    assert listed.exit_code == 0, listed.output
    assert LOCAL_SECRET not in listed.output
    assert refused.exit_code != 0
    assert "--confirm-abandon is required" in refused.output
    assert abandoned.exit_code == 0, abandoned.output

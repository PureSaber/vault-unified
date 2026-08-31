from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from vault_unified.adapters.registry import get_adapter
from vault_unified.models import PrimarySource, SecretEntry, Source, SyncStatus
from vault_unified.sync.conflict_store import (
    conflicts_path,
    legacy_conflicts_migrated,
    load_conflicts,
    mark_legacy_conflicts_migrated,
)
from vault_unified.sync.conflicts import (
    ConflictRecord,
    apply_resolution,
    default_resolution,
    new_conflict_id,
)
from vault_unified.sync.ledger import (
    AdapterCapabilities,
    PendingOperation,
    ReplicaState,
    Tombstone,
    apply_snapshot,
    capabilities_for,
    entry_snapshot,
    remote_sync_fingerprint,
)
from vault_unified.sync_prefs import load_prefs, save_prefs


class SyncOperationPending(RuntimeError):
    """A prior remote outcome is unknown and must not be retried blindly."""


@dataclass
class SyncResult:
    pulled: dict[str, dict[str, int]] = field(default_factory=dict)
    pushed: dict[str, int] = field(default_factory=dict)
    conflicts: list[ConflictRecord] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    operations: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "pulled": self.pulled,
            "pushed": self.pushed,
            "conflicts": [conflict.to_dict() for conflict in self.conflicts],
            "errors": self.errors,
            "operations": self.operations,
        }


class SyncEngine:
    def __init__(self, vault) -> None:
        self.vault = vault
        self._conflicts = self._load_embedded_conflicts()
        needs_legacy_marker = conflicts_path(self.vault_path).exists() and not (
            legacy_conflicts_migrated(self.vault_path)
        )
        legacy = load_conflicts(self.vault_path, self.vault.local.credential)
        if legacy:
            for conflict_id, record in legacy.items():
                self._conflicts.setdefault(conflict_id, record)
            self._persist_conflicts()
        if needs_legacy_marker:
            mark_legacy_conflicts_migrated(self.vault_path)

    @property
    def vault_path(self) -> Path:
        return self.vault.local.vault_path

    def _load_embedded_conflicts(self) -> dict[str, ConflictRecord]:
        result: dict[str, ConflictRecord] = {}
        for entry in self.vault.local.list_entries(include_deleted=True):
            for conflict_id, value in entry.sync_ledger.conflicts.items():
                record = ConflictRecord.from_dict(value)
                if record.id != conflict_id or record.entry_id != entry.id:
                    raise ValueError("Embedded conflict identity is inconsistent")
                if conflict_id in result:
                    raise ValueError("Embedded conflict ID is duplicated")
                result[conflict_id] = record
        return result

    def _embed_conflicts(self) -> None:
        entries = {
            entry.id: entry
            for entry in self.vault.local.list_entries(include_deleted=True)
        }
        for entry in entries.values():
            entry.sync_ledger.conflicts.clear()
        for conflict_id, record in self._conflicts.items():
            entry = entries.get(record.entry_id)
            if entry is None:
                raise ValueError("Cannot persist a conflict for a missing entry")
            entry.sync_ledger.conflicts[conflict_id] = record.to_dict(reveal=True)

    def _persist_conflicts(self) -> None:
        self._embed_conflicts()
        self.vault.local._save()

    def _record_error(self, action: str, source: Source, exc: Exception) -> None:
        self.vault._last_errors = getattr(self.vault, "_last_errors", [])
        self.vault._last_errors.append(
            f"{action} {source.value}: {type(exc).__name__}"
        )

    def get_prefs(self):
        return load_prefs(self.vault_path)

    def save_prefs(self, prefs) -> None:
        save_prefs(self.vault_path, prefs)

    def list_conflicts(self) -> list[ConflictRecord]:
        stale = [
            conflict_id
            for conflict_id, record in self._conflicts.items()
            if self.vault.local.get(record.entry_id) is None
        ]
        for conflict_id in stale:
            del self._conflicts[conflict_id]
        if stale:
            self._persist_conflicts()
        return list(self._conflicts.values())

    @staticmethod
    def _remote_revision(
        remote: SecretEntry, capabilities: AdapterCapabilities
    ) -> str:
        return remote.remote_updated_at if capabilities.revision_token else ""

    @staticmethod
    def _local_from_remote(remote: SecretEntry, source: Source) -> SecretEntry:
        snapshot = entry_snapshot(remote)
        local = SecretEntry(
            title=snapshot["title"],
            username=snapshot["username"],
            password=snapshot["password"],
            url=snapshot["url"],
            notes=snapshot["notes"],
            tags=snapshot["tags"],
            source=source,
            external_id=remote.external_id,
            proton_share_id=remote.proton_share_id,
            remote_updated_at=remote.remote_updated_at,
            sync_status=SyncStatus.CLEAN,
        )
        external_id = remote.get_linked_id(source) or remote.external_id
        if external_id:
            local.link_source(source, external_id)
        return local

    def _replica(
        self,
        entry: SecretEntry,
        source: Source,
        capabilities: AdapterCapabilities,
        external_id: str = "",
    ) -> ReplicaState:
        linked_id = external_id or entry.get_linked_id(source)
        return entry.sync_ledger.replica(source.value, linked_id, capabilities)

    @staticmethod
    def _base_remote_fingerprint(replica: ReplicaState) -> str:
        if replica.base_snapshot is None:
            return ""
        return remote_sync_fingerprint(replica.base_snapshot)

    def _remove_source_conflict(self, entry_id: str, source: Source) -> None:
        for conflict_id, record in list(self._conflicts.items()):
            if record.entry_id == entry_id and record.remote_source == source:
                del self._conflicts[conflict_id]

    def _create_conflict(
        self,
        local: SecretEntry,
        remote: SecretEntry,
        source: Source,
        replica: ReplicaState,
        *,
        remote_deleted: bool = False,
    ) -> ConflictRecord:
        self._remove_source_conflict(local.id, source)
        record = ConflictRecord(
            id=new_conflict_id(),
            entry_id=local.id,
            title=local.title,
            local=copy.deepcopy(local),
            remote=copy.deepcopy(remote),
            remote_source=source,
            default_choice=default_resolution(self.get_prefs().primary, source),
            base_snapshot=copy.deepcopy(replica.base_snapshot),
            local_revision=local.sync_ledger.content_revision,
            remote_revision=remote.remote_updated_at,
            remote_deleted=remote_deleted,
        )
        self._conflicts[record.id] = record
        local.sync_status = SyncStatus.CONFLICT
        return record

    def _accept_remote(
        self,
        local: SecretEntry,
        remote: SecretEntry,
        source: Source,
        replica: ReplicaState,
        capabilities: AdapterCapabilities,
    ) -> None:
        local_tags = list(local.tags)
        apply_snapshot(local, entry_snapshot(remote))
        local.tags = local_tags
        local.updated_at = remote.updated_at
        local.remote_updated_at = remote.remote_updated_at
        local.sync_ledger.new_content_revision()
        external_id = remote.get_linked_id(source) or remote.external_id
        if external_id:
            local.link_source(source, external_id)
            replica.external_id = external_id
        replica.record_base(
            remote,
            remote_revision=self._remote_revision(remote, capabilities),
            local_revision=local.sync_ledger.content_revision,
        )
        self._remove_source_conflict(local.id, source)

    def _refresh_status(
        self, entry: SecretEntry, required_sources: list[Source] | None = None
    ) -> None:
        if entry.sync_ledger.tombstone is not None:
            entry.sync_status = SyncStatus.DELETED_PENDING
            return
        if any(record.entry_id == entry.id for record in self._conflicts.values()):
            entry.sync_status = SyncStatus.CONFLICT
            return
        sources = list(required_sources or [])
        for value in entry.sync_ledger.replicas:
            source = Source(value)
            if source not in sources:
                sources.append(source)
        if not sources:
            entry.sync_status = SyncStatus.DIRTY
            return
        for source in sources:
            replica = entry.sync_ledger.replicas.get(source.value)
            if (
                replica is None
                or replica.pending is not None
                or replica.last_acked_local_revision
                != entry.sync_ledger.content_revision
            ):
                entry.sync_status = SyncStatus.DIRTY
                return
        if entry.sync_status != SyncStatus.CLEAN:
            entry.mark_synced()

    def _merge_remote(
        self,
        local: SecretEntry,
        remote: SecretEntry,
        source: Source,
        capabilities: AdapterCapabilities,
    ) -> str:
        external_id = remote.get_linked_id(source) or remote.external_id
        replica = self._replica(local, source, capabilities, external_id)
        local_fingerprint = remote_sync_fingerprint(local)
        remote_fingerprint = remote_sync_fingerprint(remote)
        if replica.base_snapshot is None:
            if local.sync_status in {SyncStatus.DIRTY, SyncStatus.CONFLICT} and (
                local_fingerprint != remote_fingerprint
            ):
                self._create_conflict(local, remote, source, replica)
                return "conflict"
            self._accept_remote(local, remote, source, replica, capabilities)
            return "updated"
        base_fingerprint = self._base_remote_fingerprint(replica)
        local_changed = local_fingerprint != base_fingerprint
        remote_changed = remote_fingerprint != base_fingerprint
        if not local_changed and not remote_changed:
            replica.remote_revision = self._remote_revision(remote, capabilities)
            replica.absence_state = "present"
            replica.last_acked_local_revision = local.sync_ledger.content_revision
            self._remove_source_conflict(local.id, source)
            return "unchanged"
        if remote_changed and not local_changed:
            self._accept_remote(local, remote, source, replica, capabilities)
            return "updated"
        if local_changed and not remote_changed:
            replica.absence_state = "present"
            return "local"
        if local_fingerprint == remote_fingerprint:
            replica.record_base(
                remote,
                remote_revision=self._remote_revision(remote, capabilities),
                local_revision=local.sync_ledger.content_revision,
            )
            self._remove_source_conflict(local.id, source)
            return "converged"
        self._create_conflict(local, remote, source, replica)
        return "conflict"

    def _observe_remote_absence(
        self,
        source: Source,
        seen_external_ids: set[str],
        capabilities: AdapterCapabilities,
    ) -> int:
        if not (
            capabilities.authoritative_list and capabilities.absence_is_delete
        ):
            for entry in self.vault.local.list_entries(include_deleted=True):
                replica = entry.sync_ledger.replicas.get(source.value)
                if replica and replica.external_id not in seen_external_ids:
                    replica.absence_state = "unknown"
            return 0
        observed = 0
        for entry in self.vault.local.list_entries(include_deleted=True):
            replica = entry.sync_ledger.replicas.get(source.value)
            if (
                replica is None
                or not replica.external_id
                or replica.external_id in seen_external_ids
                or entry.sync_ledger.tombstone is not None
            ):
                continue
            replica.absence_state = "deleted"
            if replica.base_snapshot is None:
                continue
            remote = self._local_from_remote(entry, source)
            apply_snapshot(remote, replica.base_snapshot)
            remote.external_id = replica.external_id
            if remote_sync_fingerprint(entry) != remote_sync_fingerprint(
                replica.base_snapshot
            ):
                self._create_conflict(
                    entry, remote, source, replica, remote_deleted=True
                )
                continue
            required = list(entry.linked_sources)
            entry.sync_ledger.tombstone = Tombstone.create(required)
            if source.value in required:
                entry.sync_ledger.tombstone.acknowledged.append(source.value)
            replica.deletion_acknowledged = True
            entry.sync_status = SyncStatus.DELETED_PENDING
            observed += 1
        return observed

    def pull_source(self, source: Source) -> dict[str, int]:
        prefs = self.get_prefs()
        if not prefs.is_source_enabled(source):
            raise RuntimeError(f"Source {source.value} is disabled in sync preferences")
        adapter = get_adapter(source)
        if not adapter.is_configured():
            return {
                "added": 0,
                "updated": 0,
                "conflicts": 0,
                "deleted_observed": 0,
                "total": 0,
            }
        if not adapter.is_available():
            raise RuntimeError(f"{adapter.name} is configured but unavailable")
        capabilities = capabilities_for(adapter)
        remote_entries = adapter.list_entries()
        external_ids = [
            remote.get_linked_id(source) or remote.external_id
            for remote in remote_entries
        ]
        if any(not external_id for external_id in external_ids) or len(
            external_ids
        ) != len(set(external_ids)):
            raise RuntimeError("Remote listing has missing or duplicate external IDs")
        before = {
            entry.id: entry.to_dict()
            for entry in self.vault.local.list_entries(include_deleted=True)
        }
        stats = {
            "added": 0,
            "updated": 0,
            "conflicts": 0,
            "deleted_observed": 0,
            "total": len(remote_entries),
        }
        for remote, external_id in zip(remote_entries, external_ids, strict=True):
            local = self.vault.local.find_by_linked_id(source, external_id)
            if local is None:
                local = self._local_from_remote(remote, source)
                replica = self._replica(local, source, capabilities, external_id)
                replica.record_base(
                    remote,
                    remote_revision=self._remote_revision(remote, capabilities),
                    local_revision=local.sync_ledger.content_revision,
                )
                local.mark_synced(remote.remote_updated_at)
                self.vault.local._entries[local.id] = local
                stats["added"] += 1
                continue
            outcome = self._merge_remote(local, remote, source, capabilities)
            if outcome == "conflict":
                stats["conflicts"] += 1
            elif outcome in {"updated", "converged"}:
                stats["updated"] += 1
            self._refresh_status(local)
        conflict_ids_before_absence = set(self._conflicts)
        stats["deleted_observed"] = self._observe_remote_absence(
            source, set(external_ids), capabilities
        )
        stats["conflicts"] += len(set(self._conflicts) - conflict_ids_before_absence)
        self._embed_conflicts()
        after = {
            entry.id: entry.to_dict()
            for entry in self.vault.local.list_entries(include_deleted=True)
        }
        if before != after:
            self.vault.local._save()
        return stats

    def _ack_replica(
        self,
        entry: SecretEntry,
        replica: ReplicaState,
        remote: SecretEntry,
        capabilities: AdapterCapabilities,
    ) -> None:
        operation = replica.pending
        replica.record_base(
            entry,
            remote_revision=self._remote_revision(remote, capabilities),
            local_revision=entry.sync_ledger.content_revision,
        )
        if operation is not None:
            replica.last_operation_id = operation.operation_id
        replica.pending = None

    def _reconcile_pending(
        self,
        entry: SecretEntry,
        source: Source,
        adapter,
        replica: ReplicaState,
        capabilities: AdapterCapabilities,
    ) -> str:
        operation = replica.pending
        if operation is None:
            return "new"
        external_id = operation.external_id or replica.external_id
        if operation.kind == "create" and not external_id:
            if capabilities.idempotent_create:
                return "retry"
            operation.state = "unknown"
            self.vault.local.replace_entry(entry)
            raise SyncOperationPending(
                "Create outcome is unknown; manual reconciliation is required"
            )
        try:
            remote = adapter.get_entry(external_id) if external_id else None
        except Exception as exc:
            operation.state = "unknown"
            self.vault.local.replace_entry(entry)
            raise SyncOperationPending(
                "Remote reconciliation is unavailable; retry is blocked"
            ) from exc
        if operation.kind == "delete":
            if remote is None and capabilities.delete_confirm:
                self._ack_delete(entry, source, replica)
                return "acknowledged"
            if remote is not None and self._base_remote_fingerprint(
                replica
            ) == remote_sync_fingerprint(remote):
                return "retry"
            operation.state = "unknown"
            self.vault.local.replace_entry(entry)
            raise SyncOperationPending(
                "Delete outcome conflicts with remote state; retry is blocked"
            )
        if remote is not None and remote_sync_fingerprint(
            remote
        ) == remote_sync_fingerprint(entry):
            self._ack_replica(entry, replica, remote, capabilities)
            self.vault.local.replace_entry(entry)
            return "acknowledged"
        if operation.kind == "update" and remote is not None and (
            self._base_remote_fingerprint(replica)
            == remote_sync_fingerprint(remote)
        ):
            return "retry"
        if operation.kind == "create" and remote is None and capabilities.idempotent_create:
            return "retry"
        operation.state = "unknown"
        self.vault.local.replace_entry(entry)
        raise SyncOperationPending(
            "Remote outcome is ambiguous; retry is blocked to prevent duplication"
        )

    def _push_content_to_source(
        self, entry: SecretEntry, source: Source, adapter
    ) -> bool:
        capabilities = capabilities_for(adapter)
        replica = self._replica(entry, source, capabilities)
        reconciliation = self._reconcile_pending(
            entry, source, adapter, replica, capabilities
        )
        if reconciliation == "acknowledged":
            return True
        external_id = replica.external_id or entry.get_linked_id(source)
        kind = "update" if external_id else "create"
        operation = replica.pending
        if operation is None:
            operation = PendingOperation.create(
                kind, entry.sync_ledger.content_revision, external_id
            )
            replica.pending = operation
            self.vault.local.replace_entry(entry)
        candidate = copy.deepcopy(entry)
        try:
            if kind == "update":
                adapter.update_entry(candidate, operation_id=operation.operation_id)
            else:
                created = adapter.create_entry(
                    candidate, operation_id=operation.operation_id
                )
                external_id = created.get_linked_id(source) or created.external_id
                if not external_id:
                    raise RuntimeError("Remote create returned no external ID")
                replica.external_id = external_id
                operation.external_id = external_id
                entry.link_source(source, external_id)
                self.vault.local.replace_entry(entry)
            remote = adapter.get_entry(external_id)
            if remote is None:
                raise RuntimeError("Remote write could not be read back")
            if remote_sync_fingerprint(remote) != remote_sync_fingerprint(entry):
                self._create_conflict(entry, remote, source, replica)
                operation.state = "unknown"
                self._persist_conflicts()
                raise RuntimeError("Remote read-back differs from the intended content")
            self._ack_replica(entry, replica, remote, capabilities)
            self.vault.local.replace_entry(entry)
            return True
        except Exception:
            if replica.pending is not None:
                replica.pending.state = "unknown"
                self.vault.local.replace_entry(entry)
            raise

    def push_entry(
        self, entry_id: str, targets: list[Source] | None = None
    ) -> dict[str, int]:
        entry = self.vault.local.get(entry_id)
        if entry is None:
            raise KeyError(entry_id)
        if entry.sync_ledger.tombstone is not None or (
            entry.sync_status == SyncStatus.DELETED_PENDING
        ):
            return self._push_delete(entry, targets)
        prefs = self.get_prefs()
        target_sources = targets or prefs.get_enabled_sources()
        pushed = 0
        errors = 0
        for source in target_sources:
            adapter = get_adapter(source)
            if not adapter.is_configured() or not adapter.is_available():
                errors += 1
                continue
            try:
                if self._push_content_to_source(entry, source, adapter):
                    pushed += 1
            except Exception as exc:
                errors += 1
                self._record_error("push", source, exc)
        self._refresh_status(entry, target_sources)
        self.vault.local.replace_entry(entry)
        return {"pushed": pushed, "errors": errors}

    def _ack_delete(
        self, entry: SecretEntry, source: Source, replica: ReplicaState
    ) -> None:
        tombstone = entry.sync_ledger.tombstone
        if tombstone is None:
            raise ValueError("Delete acknowledgement requires a tombstone")
        if source.value in tombstone.required_acknowledgements and (
            source.value not in tombstone.acknowledged
        ):
            if source.value in tombstone.abandoned:
                tombstone.abandoned.remove(source.value)
            tombstone.acknowledged.append(source.value)
        operation = replica.pending
        if operation is not None:
            replica.last_operation_id = operation.operation_id
        replica.pending = None
        replica.deletion_acknowledged = True
        replica.absence_state = "deleted"
        entry.sync_status = SyncStatus.DELETED_PENDING
        self.vault.local.replace_entry(entry)

    def _push_delete(
        self, entry: SecretEntry, targets: list[Source] | None
    ) -> dict[str, int]:
        if entry.sync_ledger.tombstone is None:
            entry.sync_ledger.tombstone = Tombstone.create(
                list(entry.linked_sources)
            )
            entry.sync_status = SyncStatus.DELETED_PENDING
            self.vault.local.replace_entry(entry)
        prefs = self.get_prefs()
        target_sources = targets or prefs.get_enabled_sources()
        pushed = 0
        errors = 0
        for source in target_sources:
            external_id = entry.get_linked_id(source)
            if not external_id:
                continue
            tombstone = entry.sync_ledger.tombstone
            if source.value in tombstone.acknowledged or (
                source.value in tombstone.abandoned
            ):
                continue
            adapter = get_adapter(source)
            if not adapter.is_configured() or not adapter.is_available():
                errors += 1
                continue
            capabilities = capabilities_for(adapter)
            replica = self._replica(entry, source, capabilities, external_id)
            try:
                reconciliation = self._reconcile_pending(
                    entry, source, adapter, replica, capabilities
                )
                if reconciliation == "acknowledged":
                    pushed += 1
                    continue
                operation = replica.pending
                if operation is None:
                    operation = PendingOperation.create(
                        "delete",
                        entry.sync_ledger.content_revision,
                        external_id,
                    )
                    replica.pending = operation
                    self.vault.local.replace_entry(entry)
                adapter.delete_entry(
                    external_id, operation_id=operation.operation_id
                )
                if not capabilities.delete_confirm:
                    raise SyncOperationPending(
                        "Adapter cannot confirm deletion; outcome remains pending"
                    )
                if adapter.get_entry(external_id) is not None:
                    raise SyncOperationPending(
                        "Remote deletion was not confirmed by read-back"
                    )
                self._ack_delete(entry, source, replica)
                pushed += 1
            except Exception as exc:
                if replica.pending is not None:
                    replica.pending.state = "unknown"
                    self.vault.local.replace_entry(entry)
                errors += 1
                self._record_error("delete", source, exc)
        return {"pushed": pushed, "errors": errors}

    def abandon_tombstone_source(self, entry_id: str, source: Source) -> None:
        entry = self.vault.local.get(entry_id)
        if entry is None or entry.sync_ledger.tombstone is None:
            raise KeyError(entry_id)
        tombstone = entry.sync_ledger.tombstone
        if source.value not in tombstone.required_acknowledgements:
            raise ValueError("Source is not required by this tombstone")
        if source.value in tombstone.acknowledged:
            raise ValueError("Source already acknowledged deletion")
        if source.value not in tombstone.abandoned:
            tombstone.abandoned.append(source.value)
        self.vault.local.replace_entry(entry)

    def purge_tombstone(
        self, entry_id: str, *, now: datetime | None = None
    ) -> None:
        entry = self.vault.local.get(entry_id)
        if entry is None or entry.sync_ledger.tombstone is None:
            raise KeyError(entry_id)
        if not entry.sync_ledger.tombstone.purge_ready(now=now):
            raise ValueError(
                "Tombstone cannot be purged before acknowledgements and retention"
            )
        self.vault.local.purge(entry_id)

    def push_all_dirty(self) -> dict[str, int]:
        total_pushed = 0
        total_errors = 0
        for entry in list(self.vault.local.list_dirty()):
            result = self.push_entry(entry.id)
            total_pushed += result["pushed"]
            total_errors += result["errors"]
        return {"pushed": total_pushed, "errors": total_errors}

    def pull_all_enabled(self) -> dict[str, dict[str, int]]:
        result: dict[str, dict[str, int]] = {}
        prefs = self.get_prefs()
        for source in prefs.get_enabled_sources():
            try:
                adapter = get_adapter(source)
                if adapter.is_configured():
                    result[source.value] = self.pull_source(source)
            except Exception as exc:
                self._record_error("pull", source, exc)
        return result

    def sync_bidirectional(self) -> SyncResult:
        result = SyncResult()
        prefs = self.get_prefs()
        sources = prefs.get_enabled_sources()
        if prefs.auto_pull_on_sync:
            for source in sources:
                try:
                    adapter = get_adapter(source)
                    if adapter.is_configured():
                        result.pulled[source.value] = self.pull_source(source)
                except Exception as exc:
                    self._record_error("pull", source, exc)
                    result.errors.append(
                        f"pull {source.value}: {type(exc).__name__}"
                    )
        if prefs.auto_push_on_edit or prefs.primary == PrimarySource.LOCAL:
            try:
                result.pushed = self.push_all_dirty()
            except Exception as exc:
                result.errors.append(f"push: {type(exc).__name__}")
        result.conflicts = self.list_conflicts()
        return result

    def resolve_conflict(
        self,
        conflict_id: str,
        choice: str,
        merged: SecretEntry | None = None,
    ) -> SecretEntry:
        record = self._conflicts.get(conflict_id)
        if record is None:
            for candidate in self._conflicts.values():
                if candidate.id.startswith(conflict_id) or candidate.entry_id.startswith(
                    conflict_id
                ):
                    record = candidate
                    conflict_id = candidate.id
                    break
        if record is None:
            raise KeyError(conflict_id)
        if choice not in {"local", "remote", "merge"}:
            raise ValueError(f"Invalid choice: {choice}")
        if choice == "merge" and merged is None:
            raise ValueError("merged entry required for merge choice")
        local = self.vault.local.get(record.entry_id)
        if local is None:
            raise KeyError(record.entry_id)
        if record.remote_deleted and choice == "remote":
            local.sync_ledger.tombstone = Tombstone.create(
                list(local.linked_sources)
            )
            tombstone = local.sync_ledger.tombstone
            if record.remote_source.value in tombstone.required_acknowledgements:
                tombstone.acknowledged.append(record.remote_source.value)
            local.sync_status = SyncStatus.DELETED_PENDING
            resolved = local
        else:
            if record.remote_deleted:
                local.linked_sources.pop(record.remote_source.value, None)
                replica = local.sync_ledger.replicas.get(
                    record.remote_source.value
                )
                if replica is not None:
                    replica.external_id = ""
                    replica.pending = None
                    replica.absence_state = "deleted"
            resolved = apply_resolution(local, record.remote, choice, merged)
            resolved.sync_ledger = local.sync_ledger
            resolved.sync_ledger.new_content_revision()
            if choice == "remote":
                replica = resolved.sync_ledger.replicas.get(
                    record.remote_source.value
                )
                if replica is None:
                    raise ValueError("Conflict has no replica ledger")
                external_id = (
                    record.remote.get_linked_id(record.remote_source)
                    or record.remote.external_id
                )
                if external_id:
                    replica.external_id = external_id
                replica.record_base(
                    record.remote,
                    remote_revision=(
                        record.remote_revision or record.remote.remote_updated_at
                    ),
                    local_revision=resolved.sync_ledger.content_revision,
                )
                operation = replica.pending
                if operation is not None:
                    replica.last_operation_id = operation.operation_id
                    replica.pending = None
        del self._conflicts[conflict_id]
        self._refresh_status(resolved)
        self.vault.local._entries[resolved.id] = resolved
        self._persist_conflicts()
        if choice in {"local", "merge"}:
            self.push_entry(resolved.id, [record.remote_source])
        return resolved

    def after_local_edit(self, entry_id: str) -> None:
        prefs = self.get_prefs()
        if prefs.auto_push_on_edit and prefs.primary == PrimarySource.LOCAL:
            self.push_entry(entry_id)

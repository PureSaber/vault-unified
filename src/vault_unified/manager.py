from __future__ import annotations

import copy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from vault_unified.adapters.bitwarden import BitwardenAdapter
from vault_unified.adapters.gopass import GopassAdapter
from vault_unified.adapters.keepassxc import KeePassXCAdapter
from vault_unified.adapters.proton_pass import ProtonPassAdapter
from vault_unified.adapters.registry import all_remote_adapters, get_adapter
from vault_unified.local_store import EntryTransactionConflict, LocalVault
from vault_unified.models import SecretEntry, Source, SyncPreferences, SyncStatus
from vault_unified.personal_data import (
    add_attachment,
    delete_attachment,
    get_attachment,
    merge_personal_metadata,
    record_history,
    restore_history,
    update_data,
)
from vault_unified.sync.engine import SyncEngine, SyncResult
from vault_unified.sync.ledger import (
    Tombstone,
    capabilities_for,
    entry_snapshot,
    remote_sync_fingerprint,
)
from vault_unified.sync.preview import canonical_digest
from vault_unified.sync_prefs import load_prefs, save_prefs
from vault_unified.v3_crypto import V3Credential


class MetadataPreservingSyncEngine(SyncEngine):
    """Keep encrypted source-specific fields without treating them as portable fields."""

    @staticmethod
    def _local_from_remote(remote: SecretEntry, source: Source) -> SecretEntry:
        local = SyncEngine._local_from_remote(remote, source)
        local.source_metadata = copy.deepcopy(remote.source_metadata)
        return local

    def _merge_remote(self, local, remote, source, capabilities) -> str:
        local_metadata = copy.deepcopy(local.source_metadata)
        outcome = super()._merge_remote(local, remote, source, capabilities)
        merged_metadata = merge_personal_metadata(local_metadata, remote.source_metadata)
        if outcome != "conflict" and local.source_metadata != merged_metadata:
            local.source_metadata = merged_metadata
            if outcome == "unchanged":
                return "updated"
        return outcome

    @staticmethod
    def _preview_pull_outcome(
        local: SecretEntry,
        remote: SecretEntry,
        source: Source,
    ) -> str:
        local_fingerprint = remote_sync_fingerprint(local)
        remote_fingerprint = remote_sync_fingerprint(remote)
        replica = local.sync_ledger.replicas.get(source.value)
        if replica is None or replica.base_snapshot is None:
            if local.sync_status in {SyncStatus.DIRTY, SyncStatus.CONFLICT} and (
                local_fingerprint != remote_fingerprint
            ):
                return "conflict"
            return "updated"

        base_fingerprint = remote_sync_fingerprint(replica.base_snapshot)
        local_changed = local_fingerprint != base_fingerprint
        remote_changed = remote_fingerprint != base_fingerprint
        if not local_changed and not remote_changed:
            return "unchanged"
        if remote_changed and not local_changed:
            return "updated"
        if local_changed and not remote_changed:
            return "local_only"
        if local_fingerprint == remote_fingerprint:
            return "converged"
        return "conflict"

    def _preview_push_counts(self, source: Source) -> dict[str, int]:
        counts = {
            "create": 0,
            "update": 0,
            "delete": 0,
            "pending": 0,
            "total": 0,
        }
        for entry in self.vault.local.list_dirty():
            replica = entry.sync_ledger.replicas.get(source.value)
            if replica is not None and replica.pending is not None:
                counts["pending"] += 1
                counts["total"] += 1
                continue

            if entry.sync_ledger.tombstone is not None or (
                entry.sync_status == SyncStatus.DELETED_PENDING
            ):
                external_id = (
                    (replica.external_id if replica is not None else "")
                    or entry.get_linked_id(source)
                )
                tombstone = entry.sync_ledger.tombstone
                if not external_id:
                    continue
                if tombstone is not None and (
                    source.value in tombstone.acknowledged
                    or source.value in tombstone.abandoned
                ):
                    continue
                counts["delete"] += 1
                counts["total"] += 1
                continue

            external_id = (
                (replica.external_id if replica is not None else "")
                or entry.get_linked_id(source)
            )
            counts["update" if external_id else "create"] += 1
            counts["total"] += 1
        return counts

    def preview_explicit(
        self,
        sources: list[Source],
        *,
        include_pull: bool,
        include_push: bool,
    ) -> dict[str, Any]:
        """Build a read-only plan. No local or remote write method is called."""
        if not include_pull and not include_push:
            raise ValueError("Preview must include pull, push, or both")
        if not sources:
            raise ValueError("At least one enabled external source is required")

        per_source: dict[str, dict[str, Any]] = {}
        digest_sources: dict[str, Any] = {}
        totals = {
            "pull_add": 0,
            "pull_update": 0,
            "pull_conflict": 0,
            "pull_delete_observed": 0,
            "push_create": 0,
            "push_update": 0,
            "push_delete": 0,
            "pending": 0,
            "unavailable_sources": 0,
        }

        for source in sources:
            adapter = get_adapter(source)
            configured = False
            available = False
            status = "not_configured"
            error = ""
            try:
                configured = adapter.is_configured()
                if configured:
                    available = adapter.is_available()
                    status = "ready" if available else "unavailable"
            except Exception as exc:
                status = "error"
                error = type(exc).__name__

            pull_counts = {
                "remote_total": 0,
                "add": 0,
                "update": 0,
                "conflict": 0,
                "unchanged": 0,
                "local_only": 0,
                "delete_observed": 0,
            }
            remote_digest_entries: list[dict[str, Any]] = []

            if include_pull and configured and available:
                try:
                    remote_entries = adapter.list_entries()
                    external_ids = [
                        remote.get_linked_id(source) or remote.external_id
                        for remote in remote_entries
                    ]
                    if any(not value for value in external_ids) or len(
                        external_ids
                    ) != len(set(external_ids)):
                        raise RuntimeError(
                            "Remote listing has missing or duplicate external IDs"
                        )
                    pull_counts["remote_total"] = len(remote_entries)
                    seen_external_ids = set(external_ids)

                    for remote, external_id in sorted(
                        zip(remote_entries, external_ids, strict=True),
                        key=lambda pair: pair[1],
                    ):
                        remote_digest_entries.append(
                            {
                                "external_id": external_id,
                                "remote_updated_at": remote.remote_updated_at,
                                "content": entry_snapshot(remote),
                                "source_metadata": remote.source_metadata,
                                "proton_share_id": remote.proton_share_id,
                            }
                        )
                        local = self.vault.local.find_by_linked_id(
                            source, external_id
                        )
                        if local is None:
                            pull_counts["add"] += 1
                            continue
                        outcome = self._preview_pull_outcome(
                            local, remote, source
                        )
                        if outcome in {"updated", "converged"}:
                            pull_counts["update"] += 1
                        elif outcome == "conflict":
                            pull_counts["conflict"] += 1
                        elif outcome == "local_only":
                            pull_counts["local_only"] += 1
                        else:
                            pull_counts["unchanged"] += 1

                    capabilities = capabilities_for(adapter)
                    if (
                        capabilities.authoritative_list
                        and capabilities.absence_is_delete
                    ):
                        for local in self.vault.local.list_entries(
                            include_deleted=True
                        ):
                            replica = local.sync_ledger.replicas.get(
                                source.value
                            )
                            if (
                                replica is None
                                or not replica.external_id
                                or replica.external_id in seen_external_ids
                                or local.sync_ledger.tombstone is not None
                                or replica.base_snapshot is None
                            ):
                                continue
                            if (
                                remote_sync_fingerprint(local)
                                != remote_sync_fingerprint(replica.base_snapshot)
                            ):
                                pull_counts["conflict"] += 1
                            else:
                                pull_counts["delete_observed"] += 1
                except Exception as exc:
                    status = "error"
                    error = type(exc).__name__
                    remote_digest_entries = []

            push_counts = (
                self._preview_push_counts(source)
                if include_push
                else {
                    "create": 0,
                    "update": 0,
                    "delete": 0,
                    "pending": 0,
                    "total": 0,
                }
            )

            if not configured or not available or status == "error":
                totals["unavailable_sources"] += 1
            totals["pull_add"] += pull_counts["add"]
            totals["pull_update"] += pull_counts["update"]
            totals["pull_conflict"] += pull_counts["conflict"]
            totals["pull_delete_observed"] += pull_counts[
                "delete_observed"
            ]
            totals["push_create"] += push_counts["create"]
            totals["push_update"] += push_counts["update"]
            totals["push_delete"] += push_counts["delete"]
            totals["pending"] += push_counts["pending"]

            source_plan = {
                "label": adapter.name,
                "configured": configured,
                "available": available,
                "status": status,
                "error": error,
                "pull": pull_counts,
                "push": push_counts,
            }
            per_source[source.value] = source_plan
            digest_sources[source.value] = {
                "plan": source_plan,
                "remote_entries": remote_digest_entries,
            }

        warnings: list[str] = []
        destructive = (
            totals["push_delete"] + totals["pull_delete_observed"]
        )
        if destructive:
            warnings.append(
                "The plan includes remote or locally observed deletions"
            )
        if totals["pending"]:
            warnings.append(
                "Some prior remote operations have an unknown outcome and "
                "require reconciliation"
            )
        if totals["unavailable_sources"]:
            warnings.append(
                "One or more selected sources are unavailable or not configured"
            )

        plan: dict[str, Any] = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "include_pull": include_pull,
            "include_push": include_push,
            "sources": [source.value for source in sources],
            "per_source": per_source,
            "totals": totals,
            "destructive_count": destructive,
            "warnings": warnings,
        }
        plan["_state_digest"] = canonical_digest(
            {
                "include_pull": include_pull,
                "include_push": include_push,
                "sources": [source.value for source in sources],
                "source_state": digest_sources,
            }
        )
        return plan

    def execute_explicit(
        self,
        sources: list[Source],
        *,
        include_pull: bool,
        include_push: bool,
    ) -> SyncResult:
        """Execute exactly the operation that an approved preview described."""
        result = SyncResult()
        if include_pull:
            for source in sources:
                try:
                    result.pulled[source.value] = self.pull_source(source)
                except Exception as exc:
                    self._record_error("pull", source, exc)
                    result.errors.append(
                        f"pull {source.value}: {type(exc).__name__}"
                    )

        if include_push:
            pushed = 0
            errors = 0
            for entry in list(self.vault.local.list_dirty()):
                stats = self.push_entry(entry.id, sources)
                pushed += stats["pushed"]
                errors += stats["errors"]
            result.pushed = {"pushed": pushed, "errors": errors}

        result.conflicts = self.list_conflicts()
        return result


class UnifiedVault:
    """Local encrypted vault with bidirectional sync to external password managers."""

    def __init__(self, vault_path: Path, credential: V3Credential) -> None:
        self.vault_path = vault_path
        self.local = LocalVault(vault_path, credential)
        self.proton = ProtonPassAdapter()
        self.bitwarden = BitwardenAdapter()
        self.keepassxc = KeePassXCAdapter()
        self.gopass = GopassAdapter()
        self.sync = MetadataPreservingSyncEngine(self)
        self._entry_transactions: dict[str, tuple[str, str]] = {}

    @classmethod
    def create(cls, vault_path: Path, password: str) -> UnifiedVault:
        LocalVault.create(vault_path, password)
        return cls(vault_path, password)

    def get_prefs(self) -> SyncPreferences:
        return load_prefs(self.vault_path)

    def save_prefs(self, prefs: SyncPreferences) -> None:
        save_prefs(self.vault_path, prefs.normalize())

    def status(self) -> dict[str, str]:
        prefs = self.get_prefs()
        enabled = {s.value for s in prefs.get_enabled_sources()}
        result = {
            "local": f"ready ({len(self.local.list_entries())} entries)",
            "dirty": str(len(self.local.list_dirty())),
            "conflicts": str(len(self.local.list_conflicts())),
        }
        for adapter in all_remote_adapters():
            tag = "enabled" if adapter.source.value in enabled else "disabled"
            result[adapter.source.value] = f"{adapter.status_message()} ({tag})"
        return result

    def list_all(self, source: Source | None = None) -> list[SecretEntry]:
        return self.local.list_entries(source=source)

    def search(self, query: str) -> list[SecretEntry]:
        return self.local.search(query)

    def get(self, entry_id: str) -> SecretEntry | None:
        return self.local.get(entry_id)

    def get_by_title(self, title: str) -> SecretEntry | None:
        return self.local.find_by_title(title)

    def resolve(self, identifier: str) -> SecretEntry:
        matches = self.local.find_matches(identifier)
        if not matches:
            raise KeyError(identifier)
        if len(matches) > 1:
            names = ", ".join(e.title for e in matches)
            raise ValueError(f"Multiple matches for '{identifier}': {names}")
        return matches[0]

    def add(
        self,
        title: str,
        username: str = "",
        password: str = "",
        url: str = "",
        notes: str = "",
        tags: list[str] | None = None,
        *,
        auto_push: bool = True,
    ) -> SecretEntry:
        entry = SecretEntry(
            title=title,
            username=username,
            password=password,
            url=url,
            notes=notes,
            tags=tags or [],
            source=Source.LOCAL,
        )
        result = self.local.add(entry)
        if auto_push:
            self.sync.after_local_edit(result.id)
        return result

    def edit(
        self,
        identifier: str,
        *,
        title: str | None = None,
        username: str | None = None,
        password: str | None = None,
        url: str | None = None,
        notes: str | None = None,
        tags: list[str] | None = None,
        auto_push: bool = True,
    ) -> SecretEntry:
        entry = self.resolve(identifier)
        result = self.local.update(
            entry.id,
            title=title,
            username=username,
            password=password,
            url=url,
            notes=notes,
            tags=tags,
        )
        if auto_push:
            self.sync.after_local_edit(result.id)
        return result

    def commit_entry_transaction(
        self,
        *,
        transaction_id: str,
        entry_id: str | None,
        expected_updated_at: str | None,
        title: str,
        username: str,
        password: str,
        url: str,
        notes: str,
        tags: list[str],
        entry_type: str,
        custom_fields: list[dict[str, Any]],
        totp_secret: str,
        add_attachments: list[dict[str, str]],
        remove_attachment_ids: list[str],
        restore_history_id: str | None,
    ) -> SecretEntry:
        """Commit the complete editor draft with one encrypted vault write."""

        receipt = self._entry_transactions.get(transaction_id)
        if receipt is not None:
            receipt_entry_id, receipt_updated_at = receipt
            current = self.local.get(receipt_entry_id)
            if current is not None and current.updated_at == receipt_updated_at:
                return current
            raise EntryTransactionConflict(
                "This save request was already used and the entry has since changed"
            )

        create = entry_id is None
        if create:
            candidate = SecretEntry(title=title, source=Source.LOCAL)
        else:
            current = self.resolve(entry_id)
            if expected_updated_at is None or current.updated_at != expected_updated_at:
                raise EntryTransactionConflict(
                    "Entry changed after this editor was opened; reload before saving"
                )
            candidate = copy.deepcopy(current)
            if restore_history_id:
                restore_history(candidate, restore_history_id)
            else:
                record_history(candidate)

        candidate.title = title
        candidate.username = username
        candidate.password = password
        candidate.url = url
        candidate.notes = notes
        candidate.tags = list(tags)
        update_data(
            candidate,
            entry_type=entry_type,
            custom_fields=custom_fields,
            totp_secret=totp_secret,
        )

        for attachment_id in remove_attachment_ids:
            get_attachment(candidate, attachment_id)
            if not delete_attachment(candidate, attachment_id):
                raise KeyError(attachment_id)
        for attachment in add_attachments:
            add_attachment(
                candidate,
                filename=attachment["filename"],
                mime_type=attachment["mime_type"],
                data_b64=attachment["data_b64"],
            )

        candidate.mark_dirty()
        committed = self.local.commit_entry(
            candidate,
            create=create,
            expected_updated_at=expected_updated_at,
        )
        self._entry_transactions[transaction_id] = (
            committed.id,
            committed.updated_at,
        )

        # The encrypted local write is the save boundary. Optional background
        # sync must not turn a successful commit into a misleading failure.
        try:
            self.sync.after_local_edit(committed.id)
        except Exception:
            pass
        return self.local.get(committed.id) or committed

    def delete(self, entry_id: str, *, soft: bool = True) -> bool:
        prefs = self.get_prefs()
        if soft:
            entry = self.local.get(entry_id)
            if entry is None:
                return False
            if entry.sync_ledger.tombstone is None:
                entry.sync_ledger.tombstone = Tombstone.create(
                    list(entry.linked_sources)
                )
            entry.mark_dirty()
            entry.sync_status = SyncStatus.DELETED_PENDING
            self.local.replace_entry(entry)
            if prefs.auto_push_on_edit:
                self.sync.push_entry(entry_id)
            return True
        return self.local.delete(entry_id, soft=False)

    def import_from_proton(self) -> dict[str, int]:
        return self.sync.pull_source(Source.PROTON_PASS)

    def import_from_bitwarden(self) -> dict[str, int]:
        return self.sync.pull_source(Source.BITWARDEN)

    def import_from_keepassxc(self) -> dict[str, int]:
        return self.sync.pull_source(Source.KEEPASSXC)

    def import_from_gopass(self) -> dict[str, int]:
        return self.sync.pull_source(Source.GOPASS)

    def sync_all(self) -> dict[str, dict[str, int]]:
        """Pull-only sync across enabled external sources."""
        return self.sync.pull_all_enabled()

    def sync_bidirectional(self) -> SyncResult:
        return self.sync.sync_bidirectional()

    def preview_sync(
        self,
        sources: list[Source],
        *,
        include_pull: bool,
        include_push: bool,
    ) -> dict[str, Any]:
        return self.sync.preview_explicit(
            sources,
            include_pull=include_pull,
            include_push=include_push,
        )

    def execute_sync(
        self,
        sources: list[Source],
        *,
        include_pull: bool,
        include_push: bool,
    ) -> SyncResult:
        return self.sync.execute_explicit(
            sources,
            include_pull=include_pull,
            include_push=include_push,
        )

    def push_entry(
        self, entry_id: str, targets: list[Source] | None = None
    ) -> dict[str, int]:
        return self.sync.push_entry(entry_id, targets)

    def push_all_dirty(
        self, targets: list[Source] | None = None
    ) -> dict[str, int]:
        pushed = 0
        errors = 0
        for entry in list(self.local.list_dirty()):
            result = self.sync.push_entry(entry.id, targets)
            pushed += result["pushed"]
            errors += result["errors"]
        return {"pushed": pushed, "errors": errors}

    def abandon_tombstone_source(
        self, entry_id: str, source: Source
    ) -> None:
        self.sync.abandon_tombstone_source(entry_id, source)

    def purge_tombstone(self, entry_id: str) -> None:
        self.sync.purge_tombstone(entry_id)

    def list_conflicts(self):
        return self.sync.list_conflicts()

    def resolve_conflict(
        self,
        conflict_id: str,
        choice: str,
        merged: SecretEntry | None = None,
    ):
        return self.sync.resolve_conflict(conflict_id, choice, merged)

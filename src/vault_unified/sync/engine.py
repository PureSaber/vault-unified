from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from vault_unified.adapters.registry import get_adapter
from vault_unified.models import PrimarySource, SecretEntry, Source, SyncStatus
from vault_unified.sync.conflict_store import load_conflicts, save_conflicts
from vault_unified.sync.conflicts import (
    ConflictRecord,
    apply_resolution,
    default_resolution,
    detect_conflict,
    new_conflict_id,
)
from vault_unified.sync_prefs import load_prefs, save_prefs


@dataclass
class SyncResult:
    pulled: dict[str, dict[str, int]] = field(default_factory=dict)
    pushed: dict[str, int] = field(default_factory=dict)
    conflicts: list[ConflictRecord] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "pulled": self.pulled,
            "pushed": self.pushed,
            "conflicts": [c.to_dict() for c in self.conflicts],
            "errors": self.errors,
        }


class SyncEngine:
    def __init__(self, vault) -> None:
        self.vault = vault
        self._conflicts: dict[str, ConflictRecord] = load_conflicts(
            self.vault_path, self.vault.local.password
        )

    @property
    def vault_path(self) -> Path:
        return self.vault.local.vault_path

    def _persist_conflicts(self) -> None:
        save_conflicts(self.vault_path, self.vault.local.password, self._conflicts)

    def get_prefs(self):
        return load_prefs(self.vault_path)

    def save_prefs(self, prefs) -> None:
        save_prefs(self.vault_path, prefs)

    def list_conflicts(self) -> list[ConflictRecord]:
        # Drop stale records whose entry is no longer CONFLICT / missing.
        stale: list[str] = []
        for cid, rec in self._conflicts.items():
            entry = self.vault.local.get(rec.entry_id)
            if not entry or entry.sync_status != SyncStatus.CONFLICT:
                stale.append(cid)
        for cid in stale:
            del self._conflicts[cid]
        if stale:
            self._persist_conflicts()
        return list(self._conflicts.values())

    def pull_source(self, source: Source) -> dict[str, int]:
        prefs = self.get_prefs()
        if not prefs.is_source_enabled(source):
            raise RuntimeError(f"Source {source.value} is disabled in sync preferences")
        adapter = get_adapter(source)
        if not adapter.is_configured():
            return {"added": 0, "updated": 0, "conflicts": 0, "total": 0}
        if not adapter.is_available():
            raise RuntimeError(f"{adapter.name} is configured but unavailable")
        remote_entries = adapter.list_entries()
        stats = {"added": 0, "updated": 0, "conflicts": 0, "total": len(remote_entries)}
        for remote in remote_entries:
            local = self.vault.local.find_by_linked_id(source, remote.external_id)
            if local and detect_conflict(local, remote):
                choice = default_resolution(prefs.primary, source)
                if prefs.conflict_default == "primary":
                    if choice == "remote" and prefs.primary != PrimarySource.LOCAL:
                        resolved = apply_resolution(local, remote, "remote")
                    else:
                        resolved = apply_resolution(local, remote, "local")
                    self.vault.local.replace_entry(resolved)
                    stats["updated"] += 1
                else:
                    local.sync_status = SyncStatus.CONFLICT
                    self.vault.local.replace_entry(local)
                    # Replace any existing conflict for this entry.
                    for existing_id, existing in list(self._conflicts.items()):
                        if existing.entry_id == local.id:
                            del self._conflicts[existing_id]
                    rec = ConflictRecord(
                        id=new_conflict_id(),
                        entry_id=local.id,
                        title=local.title,
                        local=local,
                        remote=remote,
                        remote_source=source,
                        default_choice=choice,
                    )
                    self._conflicts[rec.id] = rec
                    stats["conflicts"] += 1
            else:
                _, is_new = self.vault.local.upsert(remote, save=False, from_remote=True)
                if is_new:
                    stats["added"] += 1
                else:
                    stats["updated"] += 1
        if remote_entries:
            self.vault.local._save()
        self._persist_conflicts()
        return stats

    def push_entry(self, entry_id: str, targets: list[Source] | None = None) -> dict[str, int]:
        entry = self.vault.local.get(entry_id)
        if not entry:
            raise KeyError(entry_id)
        if entry.sync_status == SyncStatus.DELETED_PENDING:
            return self._push_delete(entry, targets)
        pushed = 0
        errors = 0
        prefs = self.get_prefs()
        target_sources = targets or prefs.get_enabled_sources()
        attempted = 0
        for source in target_sources:
            adapter = get_adapter(source)
            if not adapter.is_configured() or not adapter.is_available():
                continue
            attempted += 1
            try:
                ext_id = entry.get_linked_id(source)
                if ext_id:
                    adapter.update_entry(entry)
                else:
                    created = adapter.create_entry(entry)
                    entry.link_source(source, created.get_linked_id(source) or created.external_id)
                pushed += 1
            except Exception as exc:
                errors += 1
                self.vault._last_errors = getattr(self.vault, "_last_errors", [])
                self.vault._last_errors.append(f"{source.value}: {exc}")
        # Only mark clean when every attempted enabled target succeeded.
        if attempted and pushed == attempted and errors == 0:
            entry.mark_synced()
            self.vault.local.replace_entry(entry)
        elif pushed:
            # Partial success: keep dirty so remaining sources retry.
            self.vault.local.replace_entry(entry)
        return {"pushed": pushed, "errors": errors}

    def _push_delete(self, entry: SecretEntry, targets: list[Source] | None) -> dict[str, int]:
        pushed = 0
        errors = 0
        prefs = self.get_prefs()
        target_sources = targets or prefs.get_enabled_sources()
        remaining_links = dict(entry.linked_sources)
        for source in target_sources:
            ext_id = entry.get_linked_id(source)
            if not ext_id:
                continue
            adapter = get_adapter(source)
            if not adapter.is_available():
                errors += 1
                continue
            try:
                adapter.delete_entry(ext_id)
                pushed += 1
                remaining_links.pop(source.value, None)
            except Exception as exc:
                errors += 1
                self.vault._last_errors = getattr(self.vault, "_last_errors", [])
                self.vault._last_errors.append(f"delete {source.value}: {exc}")
        entry.linked_sources = remaining_links
        # Purge local only when no remote links remain (all deletes succeeded or none linked).
        if not remaining_links:
            self.vault.local.purge(entry.id)
        else:
            entry.sync_status = SyncStatus.DELETED_PENDING
            self.vault.local.replace_entry(entry)
        return {"pushed": pushed, "errors": errors}

    def push_all_dirty(self) -> dict[str, int]:
        total_pushed = 0
        total_errors = 0
        for entry in list(self.vault.local.list_dirty()):
            result = self.push_entry(entry.id)
            total_pushed += result["pushed"]
            total_errors += result["errors"]
        return {"pushed": total_pushed, "errors": total_errors}

    def pull_all_enabled(self) -> dict[str, dict[str, int]]:
        """Pull-only sync across enabled sources."""
        result: dict[str, dict[str, int]] = {}
        prefs = self.get_prefs()
        for source in prefs.get_enabled_sources():
            try:
                adapter = get_adapter(source)
                if adapter.is_configured():
                    result[source.value] = self.pull_source(source)
            except Exception as exc:
                self.vault._last_errors = getattr(self.vault, "_last_errors", [])
                self.vault._last_errors.append(f"pull {source.value}: {exc}")
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
                    result.errors.append(f"pull {source.value}: {exc}")
        if prefs.auto_push_on_edit or prefs.primary == PrimarySource.LOCAL:
            try:
                result.pushed = self.push_all_dirty()
            except Exception as exc:
                result.errors.append(f"push: {exc}")
        result.conflicts = self.list_conflicts()
        return result

    def resolve_conflict(
        self,
        conflict_id: str,
        choice: str,
        merged: SecretEntry | None = None,
    ) -> SecretEntry:
        record = self._conflicts.get(conflict_id)
        if not record:
            # Allow resolving by entry id prefix / full id for CLI convenience.
            for rec in self._conflicts.values():
                if rec.id.startswith(conflict_id) or rec.entry_id.startswith(conflict_id):
                    record = rec
                    conflict_id = rec.id
                    break
        if not record:
            raise KeyError(conflict_id)
        if choice not in ("local", "remote", "merge"):
            raise ValueError(f"Invalid choice: {choice}")
        if choice == "merge" and merged is None:
            raise ValueError("merged entry required for merge choice")
        resolved = apply_resolution(record.local, record.remote, choice, merged)
        self.vault.local.replace_entry(resolved)
        if choice in ("local", "merge"):
            self.push_entry(resolved.id, [record.remote_source])
        del self._conflicts[conflict_id]
        self._persist_conflicts()
        return resolved

    def after_local_edit(self, entry_id: str) -> None:
        prefs = self.get_prefs()
        if prefs.auto_push_on_edit and prefs.primary == PrimarySource.LOCAL:
            self.push_entry(entry_id)

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from vault_unified.adapters.registry import get_adapter
from vault_unified.models import PrimarySource, SecretEntry, Source, SyncStatus
from vault_unified.sync.conflicts import (
    ConflictRecord,
    apply_resolution,
    default_resolution,
    detect_conflict,
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
        self._conflicts: dict[str, ConflictRecord] = {}

    @property
    def vault_path(self) -> Path:
        return self.vault.local.vault_path

    def get_prefs(self):
        return load_prefs(self.vault_path)

    def save_prefs(self, prefs) -> None:
        save_prefs(self.vault_path, prefs)

    def list_conflicts(self) -> list[ConflictRecord]:
        stored = [c for c in self._conflicts.values()]
        for entry in self.vault.local.list_conflicts():
            if not any(c.entry_id == entry.id for c in stored):
                stored.append(
                    ConflictRecord(
                        id=str(uuid4()),
                        entry_id=entry.id,
                        title=entry.title,
                        local=entry,
                        remote=entry,
                        remote_source=entry.source,
                    )
                )
        return stored

    def pull_source(self, source: Source) -> dict[str, int]:
        adapter = get_adapter(source)
        if not adapter.is_configured():
            return {"added": 0, "updated": 0, "conflicts": 0, "total": 0}
        if not adapter.is_available():
            raise RuntimeError(f"{adapter.name} is configured but unavailable")
        remote_entries = adapter.list_entries()
        prefs = self.get_prefs()
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
                    rec = ConflictRecord(
                        id=str(uuid4()),
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
        return stats

    def push_entry(self, entry_id: str, targets: list[Source] | None = None) -> dict[str, int]:
        entry = self.vault.local.get(entry_id)
        if not entry:
            raise KeyError(entry_id)
        if entry.sync_status == SyncStatus.DELETED_PENDING:
            return self._push_delete(entry, targets)
        pushed = 0
        errors = 0
        target_sources = targets or [Source.PROTON_PASS, Source.BITWARDEN]
        for source in target_sources:
            adapter = get_adapter(source)
            if not adapter.is_configured() or not adapter.is_available():
                continue
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
                self.vault._last_errors.append(str(exc))
        if pushed:
            entry.mark_synced()
            self.vault.local.replace_entry(entry)
        return {"pushed": pushed, "errors": errors}

    def _push_delete(self, entry: SecretEntry, targets: list[Source] | None) -> dict[str, int]:
        pushed = 0
        target_sources = targets or [Source.PROTON_PASS, Source.BITWARDEN]
        for source in target_sources:
            ext_id = entry.get_linked_id(source)
            if not ext_id:
                continue
            adapter = get_adapter(source)
            if not adapter.is_available():
                continue
            try:
                adapter.delete_entry(ext_id)
                pushed += 1
            except Exception:
                pass
        self.vault.local.purge(entry.id)
        return {"pushed": pushed, "errors": 0}

    def push_all_dirty(self) -> dict[str, int]:
        total_pushed = 0
        total_errors = 0
        for entry in list(self.vault.local.list_dirty()):
            result = self.push_entry(entry.id)
            total_pushed += result["pushed"]
            total_errors += result["errors"]
        return {"pushed": total_pushed, "errors": total_errors}

    def sync_bidirectional(self) -> SyncResult:
        result = SyncResult()
        prefs = self.get_prefs()
        sources = [Source.PROTON_PASS, Source.BITWARDEN]
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
            raise KeyError(conflict_id)
        resolved = apply_resolution(record.local, record.remote, choice, merged)
        self.vault.local.replace_entry(resolved)
        if choice == "local" or choice == "merge":
            self.push_entry(resolved.id, [record.remote_source])
        del self._conflicts[conflict_id]
        return resolved

    def after_local_edit(self, entry_id: str) -> None:
        prefs = self.get_prefs()
        if prefs.auto_push_on_edit and prefs.primary == PrimarySource.LOCAL:
            self.push_entry(entry_id)

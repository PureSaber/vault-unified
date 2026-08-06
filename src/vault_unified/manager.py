from __future__ import annotations

from pathlib import Path

from vault_unified.adapters.bitwarden import BitwardenAdapter
from vault_unified.adapters.proton_pass import ProtonPassAdapter
from vault_unified.local_store import LocalVault
from vault_unified.models import SecretEntry, Source, SyncPreferences
from vault_unified.sync.engine import SyncEngine, SyncResult
from vault_unified.sync_prefs import load_prefs, save_prefs


class UnifiedVault:
    """Local encrypted vault with bidirectional sync to Proton Pass and Bitwarden."""

    def __init__(self, vault_path: Path, password: str) -> None:
        self.vault_path = vault_path
        self.local = LocalVault(vault_path, password)
        self.proton = ProtonPassAdapter()
        self.bitwarden = BitwardenAdapter()
        self.sync = SyncEngine(self)

    @classmethod
    def create(cls, vault_path: Path, password: str) -> UnifiedVault:
        LocalVault.create(vault_path, password)
        return cls(vault_path, password)

    def get_prefs(self) -> SyncPreferences:
        return load_prefs(self.vault_path)

    def save_prefs(self, prefs: SyncPreferences) -> None:
        save_prefs(self.vault_path, prefs)

    def status(self) -> dict[str, str]:
        return {
            "local": f"ready ({len(self.local.list_entries())} entries)",
            "proton_pass": self.proton.status_message(),
            "bitwarden": self.bitwarden.status_message(),
            "dirty": str(len(self.local.list_dirty())),
            "conflicts": str(len(self.local.list_conflicts())),
        }

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

    def delete(self, entry_id: str, *, soft: bool = True) -> bool:
        prefs = self.get_prefs()
        if soft and prefs.auto_push_on_edit:
            ok = self.local.delete(entry_id, soft=True)
            if ok:
                self.sync.push_entry(entry_id)
            return ok
        return self.local.delete(entry_id, soft=False)

    def import_from_proton(self) -> dict[str, int]:
        return self.sync.pull_source(Source.PROTON_PASS)

    def import_from_bitwarden(self) -> dict[str, int]:
        return self.sync.pull_source(Source.BITWARDEN)

    def sync_all(self) -> dict[str, dict[str, int]]:
        result = self.sync.sync_bidirectional()
        return result.pulled

    def sync_bidirectional(self) -> SyncResult:
        return self.sync.sync_bidirectional()

    def push_entry(self, entry_id: str, targets: list[Source] | None = None) -> dict[str, int]:
        return self.sync.push_entry(entry_id, targets)

    def push_all_dirty(self) -> dict[str, int]:
        return self.sync.push_all_dirty()

    def list_conflicts(self):
        return self.sync.list_conflicts()

    def resolve_conflict(self, conflict_id: str, choice: str, merged: SecretEntry | None = None):
        return self.sync.resolve_conflict(conflict_id, choice, merged)

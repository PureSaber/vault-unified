from __future__ import annotations

from pathlib import Path

from vault_unified.adapters.bitwarden import BitwardenAdapter
from vault_unified.adapters.gopass import GopassAdapter
from vault_unified.adapters.keepassxc import KeePassXCAdapter
from vault_unified.adapters.proton_pass import ProtonPassAdapter
from vault_unified.adapters.registry import all_remote_adapters
from vault_unified.local_store import LocalVault
from vault_unified.models import SecretEntry, Source, SyncPreferences
from vault_unified.sync.engine import SyncEngine, SyncResult
from vault_unified.sync_prefs import load_prefs, save_prefs
from vault_unified.v3_crypto import V3Credential


class UnifiedVault:
    """Local encrypted vault with bidirectional sync to external password managers."""

    def __init__(self, vault_path: Path, credential: V3Credential) -> None:
        self.vault_path = vault_path
        self.local = LocalVault(vault_path, credential)
        self.proton = ProtonPassAdapter()
        self.bitwarden = BitwardenAdapter()
        self.keepassxc = KeePassXCAdapter()
        self.gopass = GopassAdapter()
        self.sync = SyncEngine(self)

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

    def import_from_keepassxc(self) -> dict[str, int]:
        return self.sync.pull_source(Source.KEEPASSXC)

    def import_from_gopass(self) -> dict[str, int]:
        return self.sync.pull_source(Source.GOPASS)

    def sync_all(self) -> dict[str, dict[str, int]]:
        """Pull-only sync across enabled external sources."""
        return self.sync.pull_all_enabled()

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

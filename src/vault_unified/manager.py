from __future__ import annotations

from pathlib import Path

from vault_unified.adapters.bitwarden import BitwardenAdapter
from vault_unified.adapters.proton_pass import ProtonPassAdapter
from vault_unified.local_store import LocalVault
from vault_unified.models import SecretEntry, Source


class UnifiedVault:
    """Local encrypted vault with optional import from Proton Pass and Bitwarden."""

    def __init__(self, vault_path: Path, password: str) -> None:
        self.local = LocalVault(vault_path, password)
        self.proton = ProtonPassAdapter()
        self.bitwarden = BitwardenAdapter()

    @classmethod
    def create(cls, vault_path: Path, password: str) -> UnifiedVault:
        LocalVault.create(vault_path, password)
        return cls(vault_path, password)

    def status(self) -> dict[str, str]:
        return {
            "local": f"ready ({len(self.local.list_entries())} entries)",
            "proton_pass": self.proton.status_message(),
            "bitwarden": self.bitwarden.status_message(),
        }

    def list_all(self, source: Source | None = None) -> list[SecretEntry]:
        return self.local.list_entries(source=source)

    def search(self, query: str) -> list[SecretEntry]:
        return self.local.search(query)

    def get(self, entry_id: str) -> SecretEntry | None:
        return self.local.get(entry_id)

    def get_by_title(self, title: str) -> SecretEntry | None:
        return self.local.find_by_title(title)

    def add(
        self,
        title: str,
        username: str = "",
        password: str = "",
        url: str = "",
        notes: str = "",
        tags: list[str] | None = None,
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
        return self.local.add(entry)

    def delete(self, entry_id: str) -> bool:
        return self.local.delete(entry_id)

    def import_from_proton(self) -> int:
        entries = self.proton.list_entries()
        return self.local.import_entries(entries)

    def import_from_bitwarden(self) -> int:
        entries = self.bitwarden.list_entries()
        return self.local.import_entries(entries)

    def sync_all(self) -> dict[str, int]:
        results: dict[str, int] = {}
        if self.proton.is_available():
            results["proton_pass"] = self.import_from_proton()
        if self.bitwarden.is_available():
            results["bitwarden"] = self.import_from_bitwarden()
        return results

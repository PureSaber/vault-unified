from __future__ import annotations

from pathlib import Path

from vault_unified.crypto import read_encrypted_file, write_encrypted_file
from vault_unified.models import SecretEntry, Source


class LocalVault:
    """AES-GCM encrypted JSON vault stored on disk."""

    def __init__(self, vault_path: Path, password: str) -> None:
        self.vault_path = vault_path
        self.password = password
        self._entries: dict[str, SecretEntry] = {}
        if vault_path.exists():
            self._load()

    def _load(self) -> None:
        data = read_encrypted_file(self.vault_path, self.password)
        self._entries = {
            item_id: SecretEntry.from_dict(entry)
            for item_id, entry in data.get("entries", {}).items()
        }

    def _save(self) -> None:
        payload = {
            "version": 1,
            "entries": {item_id: entry.to_dict() for item_id, entry in self._entries.items()},
        }
        write_encrypted_file(self.vault_path, self.password, payload)

    @classmethod
    def create(cls, vault_path: Path, password: str) -> LocalVault:
        if vault_path.exists():
            raise FileExistsError(f"Vault already exists: {vault_path}")
        vault = cls(vault_path, password)
        vault._save()
        return vault

    def list_entries(self, source: Source | None = None) -> list[SecretEntry]:
        entries = list(self._entries.values())
        if source is not None:
            entries = [e for e in entries if e.source == source]
        return sorted(entries, key=lambda e: e.title.lower())

    def get(self, entry_id: str) -> SecretEntry | None:
        return self._entries.get(entry_id)

    def find_by_title(self, title: str) -> SecretEntry | None:
        title_lower = title.lower()
        for entry in self._entries.values():
            if entry.title.lower() == title_lower:
                return entry
        return None

    def search(self, query: str) -> list[SecretEntry]:
        q = query.lower()
        results = []
        for entry in self._entries.values():
            haystack = " ".join(
                [entry.title, entry.username, entry.url, entry.notes, *entry.tags]
            ).lower()
            if q in haystack:
                results.append(entry)
        return sorted(results, key=lambda e: e.title.lower())

    def add(self, entry: SecretEntry) -> SecretEntry:
        entry.source = Source.LOCAL
        entry.touch()
        self._entries[entry.id] = entry
        self._save()
        return entry

    def upsert(self, entry: SecretEntry) -> SecretEntry:
        """Insert or update by external_id + source, or by id."""
        existing = None
        if entry.external_id:
            for candidate in self._entries.values():
                if (
                    candidate.external_id == entry.external_id
                    and candidate.source == entry.source
                ):
                    existing = candidate
                    break
        if existing:
            entry.id = existing.id
            entry.created_at = existing.created_at
        entry.touch()
        self._entries[entry.id] = entry
        self._save()
        return entry

    def delete(self, entry_id: str) -> bool:
        if entry_id not in self._entries:
            return False
        del self._entries[entry_id]
        self._save()
        return True

    def import_entries(self, entries: list[SecretEntry]) -> int:
        count = 0
        for entry in entries:
            self.upsert(entry)
            count += 1
        return count

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

    def find_matches(self, identifier: str) -> list[SecretEntry]:
        """Find entries by exact title (case-insensitive) or id prefix."""
        identifier_lower = identifier.lower()
        matches: list[SecretEntry] = []
        for entry in self._entries.values():
            if entry.id == identifier or entry.id.startswith(identifier):
                matches.append(entry)
            elif entry.title.lower() == identifier_lower:
                matches.append(entry)
        return sorted(matches, key=lambda e: e.title.lower())

    def find_by_title(self, title: str) -> SecretEntry | None:
        matches = self.find_matches(title)
        return matches[0] if matches else None

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

    def upsert(self, entry: SecretEntry, *, save: bool = True) -> tuple[SecretEntry, bool]:
        """Insert or update by external_id + source. Returns (entry, is_new)."""
        existing = None
        if entry.external_id:
            for candidate in self._entries.values():
                if (
                    candidate.external_id == entry.external_id
                    and candidate.source == entry.source
                ):
                    existing = candidate
                    break
        is_new = existing is None
        if existing:
            entry.id = existing.id
            entry.created_at = existing.created_at
        entry.touch()
        self._entries[entry.id] = entry
        if save:
            self._save()
        return entry, is_new

    def update(
        self,
        entry_id: str,
        *,
        title: str | None = None,
        username: str | None = None,
        password: str | None = None,
        url: str | None = None,
        notes: str | None = None,
        tags: list[str] | None = None,
    ) -> SecretEntry:
        entry = self._entries.get(entry_id)
        if not entry:
            raise KeyError(entry_id)
        if title is not None:
            entry.title = title
        if username is not None:
            entry.username = username
        if password is not None:
            entry.password = password
        if url is not None:
            entry.url = url
        if notes is not None:
            entry.notes = notes
        if tags is not None:
            entry.tags = tags
        entry.touch()
        self._save()
        return entry

    def delete(self, entry_id: str) -> bool:
        if entry_id not in self._entries:
            return False
        del self._entries[entry_id]
        self._save()
        return True

    def import_entries(self, entries: list[SecretEntry]) -> dict[str, int]:
        added = 0
        updated = 0
        for entry in entries:
            _, is_new = self.upsert(entry, save=False)
            if is_new:
                added += 1
            else:
                updated += 1
        if entries:
            self._save()
        return {"added": added, "updated": updated, "total": len(entries)}

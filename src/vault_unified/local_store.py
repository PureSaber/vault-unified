from __future__ import annotations

import copy
import threading
from pathlib import Path
from typing import Any

from vault_unified.crypto import read_encrypted_file, write_encrypted_file
from vault_unified.models import SecretEntry, Source, SyncStatus
from vault_unified.storage import require_clean_storage
from vault_unified.v3_crypto import V3Credential
from vault_unified.sync.ledger import Tombstone
from vault_unified.sync.preview import canonical_digest

VAULT_VERSION = 2


class EntryTransactionConflict(ValueError):
    """The editor attempted to commit against a different entry generation."""


class LocalVault:
    """AES-GCM encrypted JSON vault stored on disk."""

    def __init__(self, vault_path: Path, credential: V3Credential) -> None:
        self.vault_path = vault_path
        self.credential = credential
        # Compatibility alias for sync sidecar encryption; it may now be a device credential.
        self.password = credential
        self._entries: dict[str, SecretEntry] = {}
        self._generation = 0
        self._lock = threading.RLock()
        require_clean_storage(vault_path)
        if vault_path.exists():
            self._load()

    def _migrate_entry(self, entry_data: dict) -> dict:
        entry_data.setdefault("sync_status", SyncStatus.CLEAN.value)
        entry_data.setdefault("last_synced_at", "")
        entry_data.setdefault("remote_updated_at", "")
        entry_data.setdefault("proton_share_id", "")
        entry_data.setdefault("linked_sources", {})
        if entry_data.get("external_id") and entry_data.get("source") not in (
            None,
            Source.LOCAL.value,
        ):
            src = entry_data["source"]
            if src not in entry_data["linked_sources"]:
                entry_data["linked_sources"][src] = entry_data["external_id"]
        return entry_data

    def _load(self) -> None:
        data = read_encrypted_file(self.vault_path, self.credential)
        version = data.get("version", 1)
        entries_raw = data.get("entries", {})
        if version < VAULT_VERSION:
            entries_raw = {
                k: self._migrate_entry(v) for k, v in entries_raw.items()
            }
        self._entries = {
            item_id: SecretEntry.from_dict(entry)
            for item_id, entry in entries_raw.items()
        }

    def _save_entries(self, entries: dict[str, SecretEntry]) -> None:
        payload = {
            "version": VAULT_VERSION,
            "entries": {item_id: entry.to_dict() for item_id, entry in entries.items()},
        }
        write_encrypted_file(self.vault_path, self.credential, payload)
        self._generation += 1

    def _save(self) -> None:
        self._save_entries(self._entries)

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    def _state_digest_locked(self) -> str:
        return canonical_digest(
            sorted(
                (entry.to_dict() for entry in self._entries.values()),
                key=lambda item: item["id"],
            )
        )

    def state_digest(self) -> str:
        with self._lock:
            return self._state_digest_locked()

    def commit_entry(
        self,
        candidate: SecretEntry,
        *,
        create: bool,
        expected_updated_at: str | None = None,
    ) -> SecretEntry:
        """Persist a prepared entry without exposing partial in-memory state."""

        with self._lock:
            current = self._entries.get(candidate.id)
            if create:
                if current is not None:
                    raise EntryTransactionConflict("Entry already exists")
            else:
                if current is None:
                    raise KeyError(candidate.id)
                if expected_updated_at is None or current.updated_at != expected_updated_at:
                    raise EntryTransactionConflict(
                        "Entry changed after this editor was opened; reload before saving"
                    )

            staged = copy.deepcopy(self._entries)
            staged[candidate.id] = copy.deepcopy(candidate)
            self._save_entries(staged)
            self._entries = staged
            return self._entries[candidate.id]

    def commit_import_batch(
        self,
        candidates: list[SecretEntry],
        *,
        updated_entry_ids: set[str],
        expected_generation: int,
        expected_digest: str,
    ) -> None:
        """Apply a previewed import with one encrypted write and no partial memory state."""

        with self._lock:
            if (
                self._generation != expected_generation
                or self._state_digest_locked() != expected_digest
            ):
                raise EntryTransactionConflict(
                    "Vault changed after the import preview; create a new preview"
                )
            candidate_ids = [entry.id for entry in candidates]
            if len(candidate_ids) != len(set(candidate_ids)):
                raise ValueError("Import contains duplicate target entries")
            for entry_id in candidate_ids:
                exists = entry_id in self._entries
                if entry_id in updated_entry_ids and not exists:
                    raise EntryTransactionConflict(
                        "An import update target no longer exists; create a new preview"
                    )
                if entry_id not in updated_entry_ids and exists:
                    raise EntryTransactionConflict(
                        "An imported entry ID already exists; create a new preview"
                    )
            staged = copy.deepcopy(self._entries)
            for candidate in candidates:
                staged[candidate.id] = copy.deepcopy(candidate)
            if candidates:
                self._save_entries(staged)
                self._entries = staged

    def restore_import_payload(
        self,
        payload: dict[str, Any],
        *,
        expected_generation: int,
        expected_digest: str,
        restored_digest: str,
    ) -> None:
        """Restore the encrypted pre-import payload as a new atomic vault generation."""

        if not isinstance(payload, dict) or not isinstance(payload.get("entries"), dict):
            raise ValueError("Import backup payload is invalid")
        entries_raw = payload["entries"]
        restored = {
            item_id: SecretEntry.from_dict(copy.deepcopy(entry))
            for item_id, entry in entries_raw.items()
        }
        candidate_digest = canonical_digest(
            sorted(
                (entry.to_dict() for entry in restored.values()),
                key=lambda item: item["id"],
            )
        )
        if candidate_digest != restored_digest:
            raise ValueError("Import backup does not match the recorded pre-import state")
        with self._lock:
            if (
                self._generation != expected_generation
                or self._state_digest_locked() != expected_digest
            ):
                raise EntryTransactionConflict(
                    "Vault changed after the import; undo was refused"
                )
            self._save_entries(restored)
            self._entries = restored

    @classmethod
    def create(cls, vault_path: Path, password: str) -> LocalVault:
        if vault_path.exists():
            raise FileExistsError(f"Vault already exists: {vault_path}")
        vault = cls(vault_path, password)
        vault._save()
        return vault

    def list_entries(
        self, source: Source | None = None, *, include_deleted: bool = False
    ) -> list[SecretEntry]:
        entries = list(self._entries.values())
        if not include_deleted:
            entries = [e for e in entries if e.sync_status != SyncStatus.DELETED_PENDING]
        if source is not None:
            entries = [e for e in entries if e.source == source]
        return sorted(entries, key=lambda e: e.title.lower())

    def list_dirty(self) -> list[SecretEntry]:
        dirty: list[SecretEntry] = []
        for entry in self._entries.values():
            if entry.sync_status == SyncStatus.DIRTY:
                dirty.append(entry)
                continue
            if entry.sync_status != SyncStatus.DELETED_PENDING:
                continue
            tombstone = entry.sync_ledger.tombstone
            if tombstone is None or tombstone.pending_sources():
                dirty.append(entry)
        return dirty

    def list_conflicts(self) -> list[SecretEntry]:
        return [e for e in self._entries.values() if e.sync_status == SyncStatus.CONFLICT]

    def get(self, entry_id: str) -> SecretEntry | None:
        return self._entries.get(entry_id)

    def find_by_linked_id(self, source: Source, external_id: str) -> SecretEntry | None:
        for entry in self._entries.values():
            if entry.get_linked_id(source) == external_id:
                return entry
            if entry.source == source and entry.external_id == external_id:
                return entry
        return None

    def find_matches(self, identifier: str) -> list[SecretEntry]:
        identifier_lower = identifier.lower()
        matches: list[SecretEntry] = []
        for entry in self._entries.values():
            if entry.sync_status == SyncStatus.DELETED_PENDING:
                continue
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
            if entry.sync_status == SyncStatus.DELETED_PENDING:
                continue
            haystack = " ".join(
                [entry.title, entry.username, entry.url, entry.notes, *entry.tags]
            ).lower()
            if q in haystack:
                results.append(entry)
        return sorted(results, key=lambda e: e.title.lower())

    def add(self, entry: SecretEntry, *, mark_dirty: bool = True) -> SecretEntry:
        with self._lock:
            entry.source = Source.LOCAL
            if mark_dirty:
                entry.mark_dirty()
            else:
                entry.touch()
            self._entries[entry.id] = entry
            self._save()
            return entry

    def upsert(
        self, entry: SecretEntry, *, save: bool = True, from_remote: bool = False
    ) -> tuple[SecretEntry, bool]:
        existing = None
        if entry.external_id and entry.source != Source.LOCAL:
            existing = self.find_by_linked_id(entry.source, entry.external_id)
        if existing is None and entry.external_id:
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
            entry.linked_sources = {**existing.linked_sources, **entry.linked_sources}
            if from_remote:
                entry.sync_status = SyncStatus.CLEAN
            elif existing.sync_status == SyncStatus.DIRTY:
                entry.sync_status = SyncStatus.CONFLICT
        elif from_remote:
            entry.sync_status = SyncStatus.CLEAN
        if not from_remote and is_new:
            entry.mark_dirty()
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
        mark_dirty: bool = True,
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
        if mark_dirty:
            entry.mark_dirty()
        else:
            entry.touch()
        self._save()
        return entry

    def replace_entry(self, entry: SecretEntry) -> SecretEntry:
        with self._lock:
            self._entries[entry.id] = entry
            self._save()
            return entry

    def mark_synced(self, entry_id: str, remote_updated_at: str = "") -> None:
        entry = self._entries.get(entry_id)
        if not entry:
            return
        entry.mark_synced(remote_updated_at)
        self._save()

    def mark_conflict(self, entry_id: str) -> None:
        entry = self._entries.get(entry_id)
        if not entry:
            return
        entry.sync_status = SyncStatus.CONFLICT
        self._save()

    def delete(self, entry_id: str, *, soft: bool = False) -> bool:
        if entry_id not in self._entries:
            return False
        if soft:
            entry = self._entries[entry_id]
            if entry.sync_ledger.tombstone is None:
                entry.sync_ledger.tombstone = Tombstone.create(
                    list(entry.linked_sources)
                )
            entry.mark_dirty()
            entry.sync_status = SyncStatus.DELETED_PENDING
            self._save()
            return True
        del self._entries[entry_id]
        self._save()
        return True

    def purge(self, entry_id: str) -> bool:
        return self.delete(entry_id, soft=False)

    def import_entries(
        self, entries: list[SecretEntry], *, from_remote: bool = True
    ) -> dict[str, int]:
        added = 0
        updated = 0
        conflicts = 0
        for entry in entries:
            _, is_new = self.upsert(entry, save=False, from_remote=from_remote)
            stored = self._entries[entry.id]
            if stored.sync_status == SyncStatus.CONFLICT:
                conflicts += 1
            elif is_new:
                added += 1
            else:
                updated += 1
        if entries:
            self._save()
        return {
            "added": added,
            "updated": updated,
            "conflicts": conflicts,
            "total": len(entries),
        }

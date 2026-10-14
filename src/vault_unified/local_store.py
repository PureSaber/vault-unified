from __future__ import annotations

import copy
import threading
from functools import wraps
from pathlib import Path
from typing import Any, Callable

from vault_unified.crypto import read_encrypted_snapshot, write_encrypted_file
from vault_unified.models import SecretEntry, Source, SyncStatus
from vault_unified.storage import require_clean_storage, ConcurrentStorageChangeError
from vault_unified.v3_crypto import V3Credential
from vault_unified.sync.ledger import Tombstone
from vault_unified.sync.preview import canonical_digest

VAULT_VERSION = 2


class EntryTransactionConflict(ValueError):
    """The editor attempted to commit against a different entry generation."""


def _local_mutation(method):
    """Legacy mutation paths participate in the same in-process transaction lock."""
    @wraps(method)
    def call(self, *args, **kwargs):
        with self._lock:
            # Deferred upserts are an implementation detail of import_entries,
            # whose outer transaction already retains the pre-import snapshot.
            previous = None if kwargs.get("save") is False else copy.deepcopy(self._entries)
            try:
                return method(self, *args, **kwargs)
            except Exception:
                if previous is not None: self._entries = previous
                raise
    return call


class LocalVault:
    """AES-GCM encrypted JSON vault stored on disk."""

    def __init__(self, vault_path: Path, credential: V3Credential) -> None:
        self.vault_path = vault_path
        self.credential = credential
        # Compatibility alias for sync sidecar encryption; it may now be a device credential.
        self.password = credential
        self._entries: dict[str, SecretEntry] = {}
        self._payload_version = VAULT_VERSION
        self._metadata: dict[str, Any] = {}
        self._generation = 0
        self._disk_revision: tuple = ()
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
        data, self._disk_revision = read_encrypted_snapshot(self.vault_path, self.credential)
        version = data.get("version", 1)
        if type(version) is not int or version not in {1, 2, 3}:
            raise ValueError("Unsupported vault payload version")
        if version == 3:
            from vault_unified.vault_format import V3Container, inspect_vault_format_file

            if not isinstance(inspect_vault_format_file(self.vault_path), V3Container):
                raise ValueError("Personal payload schema 3 requires a framed V3 vault")
        self._payload_version = max(VAULT_VERSION, version)
        self._metadata = copy.deepcopy(data.get("metadata", {}))
        entries_raw = data.get("entries", {})
        if version < VAULT_VERSION:
            entries_raw = {
                k: self._migrate_entry(v) for k, v in entries_raw.items()
            }
        self._entries = {
            item_id: SecretEntry.from_dict(entry)
            for item_id, entry in entries_raw.items()
        }

    def _payload(self, entries: dict[str, SecretEntry]) -> dict[str, Any]:
        payload = {
            "version": self._payload_version,
            "entries": {item_id: entry.to_dict() for item_id, entry in entries.items()},
        }
        if self._payload_version == 3:
            payload["metadata"] = copy.deepcopy(self._metadata)
        return payload

    def export_payload(self) -> dict[str, Any]:
        """Snapshot all encrypted data, including vault-wide personal metadata."""
        with self._lock:
            return copy.deepcopy(self._payload(self._entries))

    def metadata_value(self, namespace: str) -> Any:
        with self._lock:
            return copy.deepcopy(self._metadata.get(namespace))

    def update_metadata(self, namespace: str, transform: Callable[[Any], Any]) -> Any:
        """Commit one encrypted metadata change using the existing vault writer."""
        with self._lock:
            if self._payload_version != 3:
                raise ValueError("Upgrade the vault format before using generated-password history")
            candidate = transform(copy.deepcopy(self._metadata.get(namespace)))
            if candidate != self._metadata.get(namespace):
                metadata = {**self._metadata, namespace: candidate}
                payload = {**self._payload(self._entries), "metadata": metadata}
                self._write_payload(payload)
                self._metadata = copy.deepcopy(metadata)
                self._generation += 1
            return copy.deepcopy(candidate)

    @property
    def payload_version(self) -> int:
        return self._payload_version

    def _write_payload(self, payload: dict) -> None:
        try:
            self._disk_revision = write_encrypted_file(self.vault_path, self.credential, payload, expected_revision=self._disk_revision)
        except ConcurrentStorageChangeError:
            raise EntryTransactionConflict("Vault changed on disk; unlock again before saving") from None

    def sync_snapshot(self) -> tuple[int, dict]:
        with self._lock:
            return self._generation, self.export_payload()

    def commit_sync_payload(self, payload: dict, *, expected_generation: int) -> None:
        """Commit replicated entries and encrypted outbox/state in one write."""
        from vault_unified.v3_crypto import validate_v3_payload
        from vault_unified.personal_data import data_for, all_history
        from vault_unified.website_rules import require_website_payload
        from vault_unified.template_data import require_template_payload
        from vault_unified.passkeys import require_payload as require_passkey_payload
        candidate = copy.deepcopy(payload)
        validate_v3_payload(candidate)
        if candidate["version"] != 3:
            raise ValueError("Upgrade the vault before enabling full synchronization")
        entries = {key: SecretEntry.from_dict(value) for key, value in candidate["entries"].items()}
        for key, entry in entries.items():
            if key != entry.id:
                raise ValueError("Synchronized entry identity mismatch")
            data_for(entry); all_history(entry)
        with self._lock:
            if self._payload_version != 3 or self._generation != expected_generation:
                raise EntryTransactionConflict("Vault changed during synchronization; retry")
            require_website_payload(self, list(entries.values()))
            require_template_payload(self, list(entries.values()))
            require_passkey_payload(self, list(entries.values()))
            self._write_payload(candidate)
            self._entries = entries
            self._metadata = candidate["metadata"]
            self._generation += 1

    def _save_entries(self, entries: dict[str, SecretEntry]) -> None:
        from vault_unified.website_rules import require_website_payload
        require_website_payload(self, list(entries.values()))
        from vault_unified.template_data import require_template_payload
        require_template_payload(self, list(entries.values()))
        from vault_unified.passkeys import require_payload as require_passkey_payload
        require_passkey_payload(self, list(entries.values()))
        payload = self._payload(entries)
        self._write_payload(payload)
        self._generation += 1

    def _save(self) -> None:
        self._save_entries(self._entries)

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    def _state_digest_locked(self) -> str:
        if self._payload_version == 3:
            return canonical_digest(self._payload(self._entries))
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
        if payload.get("version") == 3:
            candidate_digest = canonical_digest({
                **payload,
                "entries": {key: entry.to_dict() for key, entry in restored.items()},
            })
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
            if max(2, payload.get("version", 2)) != self._payload_version:
                raise EntryTransactionConflict("Vault schema changed after the import")
            # An import undo must restore the complete snapshot, not only entries.
            old_metadata = self._metadata
            self._metadata = copy.deepcopy(payload.get("metadata", {}))
            try:
                self._save_entries(restored)
            except Exception:
                self._metadata = old_metadata
                raise
            self._entries = restored

    def upgrade_payload(self, *, expected_generation: int, expected_sha256: str) -> str:
        """Back up the old format, then atomically enable personal payload metadata."""
        import hashlib

        from vault_unified.backup_manager import create_manual_backup, set_backup_pinned
        from vault_unified.crypto import decrypt_payload
        from vault_unified.storage import atomic_write_bytes
        from vault_unified.v3_crypto import (
            _advance_anchor_after_write, create_v3_container, update_v3_container,
        )
        from vault_unified.vault_format import V3Container, parse_vault_container

        with self._lock:
            require_clean_storage(self.vault_path)
            source = self.vault_path.read_bytes()
            if self._generation != expected_generation or hashlib.sha256(source).hexdigest() != expected_sha256:
                raise EntryTransactionConflict("Vault changed after the upgrade preview")
            if self._payload_version == 3:
                raise ValueError("Vault already uses the personal payload format")
            if LocalVault(self.vault_path, self.credential).export_payload() != self.export_payload():
                raise EntryTransactionConflict("Vault changed on disk; unlock again")
            payload = {**self.export_payload(), "version": 3, "metadata": {}}
            container = parse_vault_container(source)
            if isinstance(container, V3Container):
                candidate = update_v3_container(self.credential, payload, container)
            else:
                if not isinstance(self.credential, str):
                    raise ValueError("Master password required to upgrade a legacy vault")
                candidate = create_v3_container(self.credential, payload)
            backup = create_manual_backup(self.vault_path, self.credential)
            set_backup_pinned(self.vault_path, backup.path, self.credential, True)
            atomic_write_bytes(
                self.vault_path, candidate,
                validator=lambda data: decrypt_payload(self.credential, data),
                expected_old_sha256=expected_sha256,
            )
            self._payload_version = 3
            self._metadata = {}
            from vault_unified.vault_format import container_revision
            self._disk_revision = container_revision(parse_vault_container(candidate))
            self._generation += 1
            _advance_anchor_after_write(self.vault_path, self.credential)
            return backup.path

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
        from vault_unified.website_rules import rules_for
        q = query.lower()
        results = []
        for entry in self._entries.values():
            if entry.sync_status == SyncStatus.DELETED_PENDING:
                continue
            haystack = " ".join(
                [entry.title, entry.username, entry.url, entry.notes, *entry.tags, *rules_for(entry)["additional_urls"]]
            ).lower()
            if q in haystack:
                results.append(entry)
        return sorted(results, key=lambda e: e.title.lower())

    @_local_mutation
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

    @_local_mutation
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

    @_local_mutation
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

    @_local_mutation
    def replace_entry(self, entry: SecretEntry) -> SecretEntry:
        with self._lock:
            self._entries[entry.id] = entry
            self._save()
            return entry

    @_local_mutation
    def mark_synced(self, entry_id: str, remote_updated_at: str = "") -> None:
        entry = self._entries.get(entry_id)
        if not entry:
            return
        entry.mark_synced(remote_updated_at)
        self._save()

    @_local_mutation
    def mark_conflict(self, entry_id: str) -> None:
        entry = self._entries.get(entry_id)
        if not entry:
            return
        entry.sync_status = SyncStatus.CONFLICT
        self._save()

    @_local_mutation
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

    @_local_mutation
    def import_entries(
        self, entries: list[SecretEntry], *, from_remote: bool = True
    ) -> dict[str, int]:
        from vault_unified.template_data import require_template_payload
        from vault_unified.website_rules import require_website_payload
        require_template_payload(self, entries)
        require_website_payload(self, entries)
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

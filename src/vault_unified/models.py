from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


class Source(str, Enum):
    LOCAL = "local"
    PROTON_PASS = "proton_pass"
    BITWARDEN = "bitwarden"


class SyncStatus(str, Enum):
    CLEAN = "clean"
    DIRTY = "dirty"
    CONFLICT = "conflict"
    DELETED_PENDING = "deleted_pending"


class PrimarySource(str, Enum):
    LOCAL = "local"
    PROTON_PASS = "proton_pass"
    BITWARDEN = "bitwarden"


@dataclass
class SecretEntry:
    """Unified secret representation across all backends."""

    title: str
    username: str = ""
    password: str = ""
    url: str = ""
    notes: str = ""
    source: Source = Source.LOCAL
    external_id: str = ""
    tags: list[str] = field(default_factory=list)
    id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    sync_status: SyncStatus = SyncStatus.DIRTY
    last_synced_at: str = ""
    remote_updated_at: str = ""
    proton_share_id: str = ""
    linked_sources: dict[str, str] = field(default_factory=dict)

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc).isoformat()
        if self.sync_status == SyncStatus.CLEAN:
            self.sync_status = SyncStatus.DIRTY

    def mark_synced(self, remote_updated_at: str = "") -> None:
        self.sync_status = SyncStatus.CLEAN
        self.last_synced_at = datetime.now(timezone.utc).isoformat()
        if remote_updated_at:
            self.remote_updated_at = remote_updated_at

    def mark_dirty(self) -> None:
        self.updated_at = datetime.now(timezone.utc).isoformat()
        self.sync_status = SyncStatus.DIRTY

    def link_source(self, source: Source, external_id: str) -> None:
        self.linked_sources[source.value] = external_id

    def get_linked_id(self, source: Source) -> str:
        return self.linked_sources.get(source.value, "")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["source"] = self.source.value
        data["sync_status"] = self.sync_status.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SecretEntry:
        source = data.get("source", Source.LOCAL.value)
        if isinstance(source, str):
            source = Source(source)
        sync_status = data.get("sync_status", SyncStatus.CLEAN.value)
        if isinstance(sync_status, str):
            sync_status = SyncStatus(sync_status)
        linked = data.get("linked_sources") or {}
        if not linked and data.get("external_id") and source != Source.LOCAL:
            linked = {source.value: data["external_id"]}
        return cls(
            id=data.get("id", str(uuid4())),
            title=data.get("title", ""),
            username=data.get("username", ""),
            password=data.get("password", ""),
            url=data.get("url", ""),
            notes=data.get("notes", ""),
            source=source,
            external_id=data.get("external_id", ""),
            tags=list(data.get("tags", [])),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            updated_at=data.get("updated_at", datetime.now(timezone.utc).isoformat()),
            sync_status=sync_status,
            last_synced_at=data.get("last_synced_at", ""),
            remote_updated_at=data.get("remote_updated_at", ""),
            proton_share_id=data.get("proton_share_id", ""),
            linked_sources=dict(linked),
        )


@dataclass
class SyncPreferences:
    primary: PrimarySource = PrimarySource.LOCAL
    auto_push_on_edit: bool = True
    auto_pull_on_sync: bool = True
    conflict_default: str = "primary"
    proton_vault_name: str = ""
    proton_share_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "primary": self.primary.value,
            "auto_push_on_edit": self.auto_push_on_edit,
            "auto_pull_on_sync": self.auto_pull_on_sync,
            "conflict_default": self.conflict_default,
            "proton_vault_name": self.proton_vault_name,
            "proton_share_id": self.proton_share_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SyncPreferences:
        primary = data.get("primary", PrimarySource.LOCAL.value)
        if isinstance(primary, str):
            primary = PrimarySource(primary)
        return cls(
            primary=primary,
            auto_push_on_edit=bool(data.get("auto_push_on_edit", True)),
            auto_pull_on_sync=bool(data.get("auto_pull_on_sync", True)),
            conflict_default=data.get("conflict_default", "primary"),
            proton_vault_name=data.get("proton_vault_name", ""),
            proton_share_id=data.get("proton_share_id", ""),
        )

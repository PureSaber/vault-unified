from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class UnlockRequest(BaseModel):
    password: str
    remember: bool = False


class UnlockResponse(BaseModel):
    token: str
    message: str = "unlocked"


class EntryOut(BaseModel):
    id: str
    title: str
    username: str = ""
    password: str = ""
    url: str = ""
    notes: str = ""
    source: str
    tags: list[str] = Field(default_factory=list)
    sync_status: str
    linked_sources: dict[str, str] = Field(default_factory=dict)
    created_at: str
    updated_at: str


class EntryIn(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    username: str = ""
    password: str = ""
    url: str = ""
    notes: str = ""
    tags: list[str] = Field(default_factory=list)


class EntryUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    username: str | None = None
    password: str | None = None
    url: str | None = None
    notes: str | None = None
    tags: list[str] | None = None


class SyncPreferencesOut(BaseModel):
    primary: str
    auto_push_on_edit: bool
    auto_pull_on_sync: bool
    conflict_default: str
    proton_vault_name: str = ""
    proton_share_id: str = ""
    enabled_sources: list[str] | None = None


class SyncPreferencesIn(BaseModel):
    primary: str | None = None
    auto_push_on_edit: bool | None = None
    auto_pull_on_sync: bool | None = None
    conflict_default: Literal["primary", "manual"] | None = None
    proton_vault_name: str | None = None
    proton_share_id: str | None = None
    enabled_sources: list[str] | None = None


class ConflictResolveIn(BaseModel):
    choice: Literal["local", "remote", "merge"]
    merged: dict[str, Any] | None = None

    @field_validator("merged")
    @classmethod
    def merge_requires_body(cls, value: dict | None, info):
        return value


class StatusOut(BaseModel):
    components: dict[str, str]

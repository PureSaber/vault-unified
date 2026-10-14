from __future__ import annotations

from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from vault_unified.api.deps import get_token, get_vault
from vault_unified.api.schemas import RestorePreviewCancelIn
from vault_unified.manager import UnifiedVault
from vault_unified.organization import prepare_action
from vault_unified.restore_preview import restore_preview_store, RestorePreviewError
from vault_unified.sync.preview import canonical_digest

router = APIRouter(prefix="/organization", tags=["organization"])


class OrganizationIn(BaseModel):
    entry_ids: list[str] = Field(min_length=1, max_length=500)
    action: Literal["trash", "archive", "restore", "purge", "favorite", "unfavorite", "tag"]
    tags: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("entry_ids")
    @classmethod
    def unique_ids(cls, value):
        if len(set(value)) != len(value) or any(not item or len(item) > 128 for item in value):
            raise ValueError("Select unique entry identifiers")
        return value

    @field_validator("tags")
    @classmethod
    def bounded_tags(cls, value):
        if any(not tag.strip() or len(tag) > 100 for tag in value):
            raise ValueError("Tags must contain 1 to 100 characters")
        return list(dict.fromkeys(tag.strip() for tag in value))


class OrganizationApplyIn(OrganizationIn):
    preview_token: str = Field(min_length=32, max_length=512)
    confirm: bool = False


def candidates(vault, body):
    if vault.local.payload_version < 3:
        raise ValueError("Upgrade the vault in Security & recovery to use account organization")
    result = []
    for entry_id in body.entry_ids:
        entry = vault.local.get(entry_id)
        if entry is None:
            raise ValueError("An entry no longer exists; refresh the list")
        result.append(prepare_action(entry, body.action, tags=body.tags))
    return result


def operation_digest(body):
    return canonical_digest(body.model_dump(include={"entry_ids", "action", "tags"}))


@router.post("/preview")
def preview(body: OrganizationIn, vault: UnifiedVault = Depends(get_vault), token: str = Depends(get_token)):
    try:
        generation, digest = vault.local.generation, vault.local.state_digest()
        candidates(vault, body)
        intent = restore_preview_store.issue(scope=token, kind="organization", source_path="",
            source_sha256=operation_digest(body), active_sha256="", active_state_digest=digest, active_generation=generation)
        return {"preview_token": intent.token, "action": body.action,
                "entries": [{"id": entry_id, "title": vault.local.get(entry_id).title} for entry_id in body.entry_ids]}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/cancel")
def cancel(body: RestorePreviewCancelIn, vault: UnifiedVault = Depends(get_vault), token: str = Depends(get_token)):
    try:
        restore_preview_store.consume(body.preview_token, scope=token, kind="organization")
    except RestorePreviewError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"cancelled": True}


@router.post("/apply")
def apply(body: OrganizationApplyIn, vault: UnifiedVault = Depends(get_vault), token: str = Depends(get_token)):
    if not body.confirm:
        raise HTTPException(status_code=400, detail="Confirm the reviewed organization changes")
    try:
        intent = restore_preview_store.consume(body.preview_token, scope=token, kind="organization")
        if operation_digest(body) != intent.source_sha256:
            raise ValueError("Organization selection changed after preview")
        prepared = candidates(vault, body)
        vault.local.commit_import_batch(prepared, updated_entry_ids=set(body.entry_ids),
            expected_generation=intent.active_generation, expected_digest=intent.active_state_digest)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"changed": len(prepared)}

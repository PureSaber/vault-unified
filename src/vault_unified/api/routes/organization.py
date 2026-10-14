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
from vault_unified.duplicate_merge import duplicate_groups, prepare_merge
from vault_unified.personal_data import public_data

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


class MergeIn(BaseModel):
    target_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(min_length=1, max_length=128)
    choices: dict[str, Literal["target", "source"]] = Field(max_length=10)


class MergeApplyIn(MergeIn):
    preview_token: str = Field(min_length=32, max_length=512)
    confirm: bool = False


def merge_candidates(vault, body):
    if vault.local.payload_version < 3:
        raise ValueError("Upgrade the vault in Security & recovery before merging accounts")
    target, source = vault.local.get(body.target_id), vault.local.get(body.source_id)
    if not target or not source:
        raise ValueError("An account no longer exists; refresh the list")
    return prepare_merge(target, source, body.choices)


def merge_digest(body):
    return canonical_digest(body.model_dump(include={"target_id", "source_id", "choices"}))


@router.get("/duplicates")
def duplicates(vault: UnifiedVault = Depends(get_vault)):
    return {"groups": duplicate_groups(vault.local.list_entries())}


@router.post("/merge/preview")
def preview_merge(body: MergeIn, vault: UnifiedVault = Depends(get_vault), token: str = Depends(get_token)):
    try:
        generation, digest = vault.local.generation, vault.local.state_digest()
        candidate, source = merge_candidates(vault, body)
        intent = restore_preview_store.issue(scope=token, kind="duplicate-merge", source_path="",
            source_sha256=merge_digest(body), active_sha256="", active_state_digest=digest, active_generation=generation)
        info = public_data(candidate, reveal=False)
        return {"preview_token": intent.token, "target_title": candidate.title, "source_title": source.title,
                "history_count": info["history_count"], "attachment_count": len(info["attachments"])}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/merge/cancel")
def cancel_merge(body: RestorePreviewCancelIn, vault: UnifiedVault = Depends(get_vault), token: str = Depends(get_token)):
    try:
        restore_preview_store.consume(body.preview_token, scope=token, kind="duplicate-merge")
    except RestorePreviewError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"cancelled": True}


@router.post("/merge/apply")
def apply_merge(body: MergeApplyIn, vault: UnifiedVault = Depends(get_vault), token: str = Depends(get_token)):
    if not body.confirm:
        raise HTTPException(status_code=400, detail="Confirm the reviewed account merge")
    try:
        intent = restore_preview_store.consume(body.preview_token, scope=token, kind="duplicate-merge")
        if merge_digest(body) != intent.source_sha256:
            raise ValueError("Field choices changed after preview")
        prepared = merge_candidates(vault, body)
        vault.local.commit_import_batch(prepared, updated_entry_ids={body.target_id, body.source_id},
            expected_generation=intent.active_generation, expected_digest=intent.active_state_digest)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"merged_id": body.target_id, "trashed_id": body.source_id}

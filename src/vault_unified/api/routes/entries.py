from __future__ import annotations

import copy
from uuid import UUID, uuid4
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from vault_unified.api.deps import get_vault
from vault_unified.api.schemas import (
    AttachmentIn,
    EntryIn,
    EntryOut,
    EntryTransactionIn,
    EntryUpdate,
)
from vault_unified.clipboard import copy_to_clipboard
from vault_unified.generator import generate_password
from vault_unified.generation_history import generate_saved, list_generated, get_generated
from vault_unified.local_store import EntryTransactionConflict
from vault_unified.manager import UnifiedVault
from vault_unified.models import SecretEntry, Source
from vault_unified.organization import organization_for, is_fillable
from vault_unified.template_data import template_for
from vault_unified.website_rules import normalize_rules, validate_rules, matches_rules, website
from vault_unified.totp import current_totp, TotpError
from vault_unified.personal_data import (
    PersonalDataError,
    data_for,
    get_attachment,
    list_history,
    public_data,
    record_history,
    restore_history,
)

router = APIRouter(prefix="/entries", tags=["entries"])


class AutoTypeIn(BaseModel):
    entry_id: UUID


@router.post("/tools/auto-type")
def auto_type_values(body: AutoTypeIn, response: Response, vault: UnifiedVault = Depends(get_vault)) -> dict:
    response.headers["Cache-Control"] = "no-store"
    entry = vault.local.get(str(body.entry_id))
    try:
        allowed = entry is not None and is_fillable(entry) and data_for(entry)["entry_type"] == "login"
    except ValueError:
        allowed = False
    if not allowed:
        raise HTTPException(status_code=400, detail="Choose an active login for automatic typing")
    values = (entry.username, entry.password)
    if any(len(value) > 256 or any(ord(char) < 32 or ord(char) == 127 for char in value) for value in values):
        raise HTTPException(status_code=400, detail="This login cannot be typed automatically")
    return {"username": entry.username, "password": entry.password}


class TotpPreviewIn(BaseModel):
    value: str = Field(max_length=1024, repr=False)


@router.post("/tools/totp/preview")
def preview_totp(body: TotpPreviewIn, response: Response, vault: UnifiedVault = Depends(get_vault)) -> dict:
    response.headers["Cache-Control"] = "no-store"
    try:
        return {"valid": True, **current_totp(body.value)}
    except TotpError:
        return {"valid": False}


@router.get("/{entry_id}/totp")
def entry_totp(entry_id: str, response: Response, vault: UnifiedVault = Depends(get_vault)) -> dict:
    response.headers["Cache-Control"] = "no-store"
    try:
        entry = vault.resolve(entry_id)
        return current_totp(data_for(entry)["totp_secret"])
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="This entry has no valid authenticator key") from exc


@router.post("/{entry_id}/totp/copy")
def copy_totp(entry_id: str, response: Response, vault: UnifiedVault = Depends(get_vault)) -> dict:
    import math
    result = entry_totp(entry_id, response, vault)
    seconds = min(45, max(1, math.ceil(result["remaining_seconds"])))
    copy_to_clipboard(result["code"], clear_after=seconds)
    return {"copied": "totp", "clears_in_seconds": seconds}


def _to_out(entry: SecretEntry, *, reveal: bool = False) -> EntryOut:
    organization = organization_for(entry)
    return EntryOut(
        id=entry.id,
        title=entry.title,
        username=entry.username,
        password=entry.password if reveal else "",
        url=entry.url,
        notes=entry.notes if reveal else "",
        has_password=bool(entry.password),
        has_notes=bool(entry.notes),
        source=entry.source.value,
        tags=entry.tags,
        sync_status=entry.sync_status.value,
        linked_sources=entry.linked_sources,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
        state=organization["state"], favorite=organization["favorite"], trashed_at=organization["trashed_at"],
        **public_data(entry, reveal=reveal),
    )


def _commit(vault: UnifiedVault, body: EntryTransactionIn) -> SecretEntry:
    try:
        return vault.commit_entry_transaction(
            transaction_id=body.transaction_id,
            entry_id=body.entry_id,
            expected_updated_at=body.expected_updated_at,
            title=body.title,
            username=body.username,
            password=body.password,
            url=body.url,
            notes=body.notes,
            tags=body.tags,
            entry_type=body.entry_type,
            custom_fields=body.custom_fields,
            totp_secret=body.totp_secret,
            add_attachments=[item.model_dump() for item in body.add_attachments],
            remove_attachment_ids=body.remove_attachment_ids,
            restore_history_id=body.restore_history_id,
            template_data=body.template_data,
            website_rules=body.website_rules,
        )
    except EntryTransactionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PersonalDataError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail="Entry draft references missing data",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Entry was not saved; no changes were committed",
        ) from exc


@router.get("/tools/generate")
def generate(
    response: Response,
    length: int = Query(default=20, ge=8, le=128),
    symbols: bool = Query(default=True),
    vault: UnifiedVault = Depends(get_vault),
) -> dict:
    response.headers["Cache-Control"] = "no-store"
    pwd = generate_password(length, symbols=symbols)
    return {"password": pwd}


class GenerationIn(BaseModel):
    kind: Literal["password", "passphrase"] = "password"
    length: int = Field(default=20, ge=8, le=128)
    symbols: bool = True
    digits: bool = True
    upper: bool = True
    lower: bool = True
    allowed: str = Field(default="", max_length=128)
    excluded: str = Field(default="", max_length=128)
    words: int = Field(default=6, ge=6, le=12)
    separator: Literal["-", " ", ".", "_"] = "-"
    url: str = Field(default="", max_length=2048)
    request_id: UUID | None = None


@router.post("/tools/generate")
def generate_with_history(body: GenerationIn, response: Response, vault: UnifiedVault = Depends(get_vault)) -> dict:
    response.headers["Cache-Control"] = "no-store"
    try:
        return generate_saved(vault.local, **body.model_dump(mode="json"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Generated password was not saved; try again") from exc


@router.get("/tools/generation/history")
def generation_history(response: Response, vault: UnifiedVault = Depends(get_vault)) -> dict:
    response.headers["Cache-Control"] = "no-store"
    return {"items": list_generated(vault.local)}


@router.get("/tools/generation/history/{record_id}")
def generation_value(record_id: str, response: Response, vault: UnifiedVault = Depends(get_vault)) -> dict:
    response.headers["Cache-Control"] = "no-store"
    try:
        return {"password": get_generated(vault.local, record_id)["value"]}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Generated password expired or was not found") from exc


@router.post("/tools/generation/history/{record_id}/copy")
def copy_generation(record_id: str, response: Response, vault: UnifiedVault = Depends(get_vault)) -> dict:
    value = generation_value(record_id, response, vault)["password"]
    copy_to_clipboard(value, clear_after=45)
    return {"copied": True, "clears_in_seconds": 45}


class WebsiteMatchIn(BaseModel):
    primary_url: str = Field(default="", max_length=2048)
    rules: dict = Field(default_factory=dict)
    test_url: str = Field(max_length=2048)


@router.post("/tools/website-match")
def test_website_match(body: WebsiteMatchIn, vault: UnifiedVault = Depends(get_vault)) -> dict:
    try:
        rules = normalize_rules(body.rules)
        validate_rules(body.primary_url, rules)
        return {"valid": True, "matches": matches_rules(body.primary_url, rules, website(body.test_url))}
    except ValueError:
        return {"valid": False, "matches": False}


@router.get("", response_model=list[EntryOut])
def list_entries(
    source: str | None = None,
    q: str | None = None,
    state: Literal["active", "archived", "trash", "all"] = "active",
    vault: UnifiedVault = Depends(get_vault),
) -> list[EntryOut]:
    if q:
        entries = vault.search(q)
    else:
        src = None
        if source:
            try:
                src = Source(source)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="Invalid source") from exc
        entries = vault.list_all(source=src)
    return [_to_out(e) for e in entries if state == "all" or organization_for(e)["state"] == state]


@router.get("/{entry_id}", response_model=EntryOut)
def get_entry(
    entry_id: str,
    reveal: bool = Query(default=False),
    vault: UnifiedVault = Depends(get_vault),
) -> EntryOut:
    entry = vault.get(entry_id)
    if not entry:
        try:
            entry = vault.resolve(entry_id)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=404, detail="Not found") from exc
    return _to_out(entry, reveal=reveal)


@router.post("", response_model=EntryOut)
def create_entry(body: EntryIn, vault: UnifiedVault = Depends(get_vault)) -> EntryOut:
    entry = _commit(
        vault,
        EntryTransactionIn(
            transaction_id=str(uuid4()),
            title=body.title,
            username=body.username,
            password=body.password,
            url=body.url,
            notes=body.notes,
            tags=body.tags,
            entry_type=body.entry_type,
            template_data=body.template_data,
            website_rules=body.website_rules,
            custom_fields=body.custom_fields,
            totp_secret=body.totp_secret,
        ),
    )
    return _to_out(entry, reveal=True)


@router.post("/commit", response_model=EntryOut)
def commit_entry_transaction(
    body: EntryTransactionIn,
    vault: UnifiedVault = Depends(get_vault),
) -> EntryOut:
    return _to_out(_commit(vault, body), reveal=True)


@router.patch("/{entry_id}", response_model=EntryOut)
def update_entry(
    entry_id: str,
    body: EntryUpdate,
    vault: UnifiedVault = Depends(get_vault),
) -> EntryOut:
    try:
        existing = vault.resolve(entry_id)
        personal = data_for(existing)
        entry = _commit(
            vault,
            EntryTransactionIn(
                transaction_id=str(uuid4()),
                entry_id=existing.id,
                expected_updated_at=existing.updated_at,
                title=body.title if body.title is not None else existing.title,
                username=body.username if body.username is not None else existing.username,
                password=body.password if body.password is not None else existing.password,
                url=body.url if body.url is not None else existing.url,
                notes=body.notes if body.notes is not None else existing.notes,
                tags=body.tags if body.tags is not None else existing.tags,
                entry_type=body.entry_type if body.entry_type is not None else personal["entry_type"],
                template_data=body.template_data,
                website_rules=body.website_rules,
                custom_fields=body.custom_fields if body.custom_fields is not None else personal["custom_fields"],
                totp_secret=body.totp_secret if body.totp_secret is not None else personal["totp_secret"],
            ),
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _to_out(entry, reveal=True)


@router.delete("/{entry_id}")
def delete_entry(entry_id: str, vault: UnifiedVault = Depends(get_vault)) -> dict:
    if vault.local.payload_version >= 3:
        raise HTTPException(status_code=409, detail="Use a trash preview to delete this entry")
    try:
        entry = vault.resolve(entry_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    record_history(entry)
    vault.local.replace_entry(entry)
    vault.delete(entry.id)
    return {"deleted": entry.title}


@router.get("/{entry_id}/history")
def entry_history(
    entry_id: str,
    reveal: bool = Query(default=False),
    vault: UnifiedVault = Depends(get_vault),
) -> dict:
    try:
        entry = vault.resolve(entry_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="Not found") from exc
    return {"history": list_history(entry, reveal=reveal)}


@router.post("/{entry_id}/history/{history_id}/restore", response_model=EntryOut)
def restore_entry_history(
    entry_id: str,
    history_id: str,
    vault: UnifiedVault = Depends(get_vault),
) -> EntryOut:
    _ = (entry_id, history_id, vault)
    raise HTTPException(
        status_code=409,
        detail="History restoration must be previewed in the editor and saved as one transaction",
    )


@router.get("/{entry_id}/history/{history_id}")
def preview_entry_history(
    entry_id: str,
    history_id: str,
    vault: UnifiedVault = Depends(get_vault),
) -> dict:
    try:
        entry = copy.deepcopy(vault.resolve(entry_id))
        restore_history(entry, history_id)
    except PersonalDataError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="History version not found") from exc
    return {"history_id": history_id, "entry": _to_out(entry, reveal=True)}


@router.post("/{entry_id}/attachments")
def create_attachment(
    entry_id: str,
    body: AttachmentIn,
    vault: UnifiedVault = Depends(get_vault),
) -> dict:
    try:
        existing = vault.resolve(entry_id)
        existing_ids = {item["id"] for item in public_data(existing, reveal=True)["attachments"]}
        personal = data_for(existing)
        entry = _commit(
            vault,
            EntryTransactionIn(
                transaction_id=str(uuid4()),
                entry_id=existing.id,
                expected_updated_at=existing.updated_at,
                title=existing.title,
                username=existing.username,
                password=existing.password,
                url=existing.url,
                notes=existing.notes,
                tags=existing.tags,
                entry_type=personal["entry_type"],
                custom_fields=personal["custom_fields"],
                totp_secret=personal["totp_secret"],
                add_attachments=[body],
            ),
        )
        attachment = next(
            item
            for item in public_data(entry, reveal=True)["attachments"]
            if item["id"] not in existing_ids
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"attachment": attachment, "entry": _to_out(entry, reveal=True)}


@router.get("/{entry_id}/attachments/{attachment_id}")
def download_attachment(
    entry_id: str,
    attachment_id: str,
    vault: UnifiedVault = Depends(get_vault),
) -> dict:
    try:
        entry = vault.resolve(entry_id)
        attachment = get_attachment(entry, attachment_id)
    except (KeyError, ValueError, PersonalDataError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return dict(attachment)


@router.delete("/{entry_id}/attachments/{attachment_id}")
def remove_attachment(
    entry_id: str,
    attachment_id: str,
    vault: UnifiedVault = Depends(get_vault),
) -> dict:
    try:
        existing = vault.resolve(entry_id)
        personal = data_for(existing)
        entry = _commit(
            vault,
            EntryTransactionIn(
                transaction_id=str(uuid4()),
                entry_id=existing.id,
                expected_updated_at=existing.updated_at,
                title=existing.title,
                username=existing.username,
                password=existing.password,
                url=existing.url,
                notes=existing.notes,
                tags=existing.tags,
                entry_type=personal["entry_type"],
                custom_fields=personal["custom_fields"],
                totp_secret=personal["totp_secret"],
                remove_attachment_ids=[attachment_id],
            ),
        )
    except (KeyError, ValueError, PersonalDataError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"deleted": attachment_id, "entry": _to_out(entry, reveal=True)}


@router.post("/{entry_id}/copy")
def copy_field(
    entry_id: str,
    field: str = Query(default="password"),
    vault: UnifiedVault = Depends(get_vault),
) -> dict:
    if field not in ("password", "username"):
        raise HTTPException(status_code=400, detail="field must be password or username")
    try:
        entry = vault.resolve(entry_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    value = entry.password if field == "password" else entry.username
    if not value:
        raise HTTPException(status_code=400, detail=f"No {field}")
    copy_to_clipboard(value)
    return {"copied": field, "title": entry.title, "clears_in_seconds": 45}


@router.post("/{entry_id}/recovery-codes/{code_id}/copy")
def copy_recovery_code(entry_id: str, code_id: str, vault: UnifiedVault = Depends(get_vault)) -> dict:
    try:
        entry = vault.resolve(entry_id)
        code = next((item for item in template_for(entry).get("recovery_codes", []) if item["id"] == code_id), None)
        if code is None:
            raise KeyError("Recovery code not found")
        if code["used_at"]:
            raise HTTPException(status_code=409, detail="This recovery code is marked used")
        copy_to_clipboard(code["value"])
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Recovery code not found") from exc
    return {"copied": "recovery_code", "clears_in_seconds": 45}

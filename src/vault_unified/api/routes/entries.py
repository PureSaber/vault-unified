from __future__ import annotations

import copy
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query

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
from vault_unified.local_store import EntryTransactionConflict
from vault_unified.manager import UnifiedVault
from vault_unified.models import SecretEntry, Source
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


def _to_out(entry: SecretEntry, *, reveal: bool = False) -> EntryOut:
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
        )
    except EntryTransactionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PersonalDataError as exc:
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
    length: int = Query(default=20, ge=8, le=128),
    symbols: bool = Query(default=True),
    vault: UnifiedVault = Depends(get_vault),
) -> dict:
    _ = vault
    pwd = generate_password(length, symbols=symbols)
    return {"password": pwd}


@router.get("", response_model=list[EntryOut])
def list_entries(
    source: str | None = None,
    q: str | None = None,
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
    return [_to_out(e) for e in entries]


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
                custom_fields=body.custom_fields if body.custom_fields is not None else personal["custom_fields"],
                totp_secret=body.totp_secret if body.totp_secret is not None else personal["totp_secret"],
            ),
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _to_out(entry, reveal=True)


@router.delete("/{entry_id}")
def delete_entry(entry_id: str, vault: UnifiedVault = Depends(get_vault)) -> dict:
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

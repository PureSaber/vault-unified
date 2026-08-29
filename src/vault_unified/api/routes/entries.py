from __future__ import annotations

import copy

from fastapi import APIRouter, Depends, HTTPException, Query

from vault_unified.api.deps import get_vault
from vault_unified.api.schemas import AttachmentIn, EntryIn, EntryOut, EntryUpdate
from vault_unified.clipboard import copy_to_clipboard
from vault_unified.generator import generate_password
from vault_unified.manager import UnifiedVault
from vault_unified.models import SecretEntry, Source
from vault_unified.personal_data import (
    PersonalDataError,
    add_attachment,
    data_for,
    delete_attachment,
    get_attachment,
    list_history,
    public_data,
    record_history,
    restore_history,
    set_data,
    update_data,
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
    # Validate personal-only data before the normal entry is ever persisted.
    candidate = SecretEntry(title=body.title)
    try:
        update_data(
            candidate,
            entry_type=body.entry_type,
            custom_fields=body.custom_fields,
            totp_secret=body.totp_secret,
        )
    except PersonalDataError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    entry = vault.add(
        body.title,
        body.username,
        body.password,
        body.url,
        body.notes,
        body.tags,
        auto_push=False,
    )
    entry.source_metadata = candidate.source_metadata
    vault.local.replace_entry(entry)
    vault.sync.after_local_edit(entry.id)
    return _to_out(entry, reveal=True)


@router.patch("/{entry_id}", response_model=EntryOut)
def update_entry(
    entry_id: str,
    body: EntryUpdate,
    vault: UnifiedVault = Depends(get_vault),
) -> EntryOut:
    try:
        existing = vault.resolve(entry_id)
        # Do not leave ordinary fields half-updated if an extension field is
        # invalid.  Keep the validated desired extension separate so the
        # current-state history can be recorded immediately before persistence.
        candidate = copy.deepcopy(existing)
        update_data(
            candidate,
            entry_type=body.entry_type,
            custom_fields=body.custom_fields,
            totp_secret=body.totp_secret,
        )
        desired_personal = data_for(candidate)
        if body.model_fields_set:
            record_history(existing)
        entry = vault.edit(
            entry_id,
            title=body.title,
            username=body.username,
            password=body.password,
            url=body.url,
            notes=body.notes,
            tags=body.tags,
            auto_push=False,
        )
        desired_personal["history"] = data_for(entry)["history"]
        set_data(entry, desired_personal)
        vault.local.replace_entry(entry)
        vault.sync.after_local_edit(entry.id)
    except PersonalDataError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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
    try:
        entry = vault.resolve(entry_id)
        restore_history(entry, history_id)
        entry.mark_dirty()
        vault.local.replace_entry(entry)
        vault.sync.after_local_edit(entry.id)
    except PersonalDataError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _to_out(entry, reveal=True)


@router.post("/{entry_id}/attachments")
def create_attachment(
    entry_id: str,
    body: AttachmentIn,
    vault: UnifiedVault = Depends(get_vault),
) -> dict:
    try:
        entry = vault.resolve(entry_id)
        # Validate binary size and encoding on a copy first, so a malformed
        # upload cannot create a ghost history record in the in-memory vault.
        candidate = copy.deepcopy(entry)
        attachment = add_attachment(
            candidate,
            filename=body.filename,
            mime_type=body.mime_type,
            data_b64=body.data_b64,
        )
        record_history(entry)
        candidate_personal = data_for(candidate)
        candidate_personal["history"] = data_for(entry)["history"]
        set_data(entry, candidate_personal)
        entry.mark_dirty()
        vault.local.replace_entry(entry)
        vault.sync.after_local_edit(entry.id)
    except PersonalDataError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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
        entry = vault.resolve(entry_id)
        get_attachment(entry, attachment_id)
        record_history(entry)
        if not delete_attachment(entry, attachment_id):
            raise KeyError("attachment not found")
        entry.mark_dirty()
        vault.local.replace_entry(entry)
        vault.sync.after_local_edit(entry.id)
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

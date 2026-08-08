from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from vault_unified.api.deps import get_vault
from vault_unified.api.schemas import EntryIn, EntryOut, EntryUpdate
from vault_unified.clipboard import copy_to_clipboard
from vault_unified.crypto import mask_secret
from vault_unified.generator import generate_password
from vault_unified.manager import UnifiedVault
from vault_unified.models import SecretEntry, Source

router = APIRouter(prefix="/entries", tags=["entries"])


def _to_out(entry: SecretEntry, *, reveal: bool = False) -> EntryOut:
    return EntryOut(
        id=entry.id,
        title=entry.title,
        username=entry.username,
        password=entry.password if reveal else mask_secret(entry.password),
        url=entry.url,
        notes=entry.notes if reveal else mask_secret(entry.notes, visible=0),
        source=entry.source.value,
        tags=entry.tags,
        sync_status=entry.sync_status.value,
        linked_sources=entry.linked_sources,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
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
    entry = vault.add(
        body.title,
        body.username,
        body.password,
        body.url,
        body.notes,
        body.tags,
    )
    return _to_out(entry, reveal=True)


@router.patch("/{entry_id}", response_model=EntryOut)
def update_entry(
    entry_id: str,
    body: EntryUpdate,
    vault: UnifiedVault = Depends(get_vault),
) -> EntryOut:
    password = body.password
    notes = body.notes
    # Ignore masked placeholder payloads from the desktop list view.
    if password is not None and (
        set(password) <= {"*", "•"} or "****" in password or password.startswith("•")
    ):
        password = None
    if notes is not None and (set(notes) <= {"*", "•"} or notes.startswith("•")):
        notes = None
    try:
        entry = vault.edit(
            entry_id,
            title=body.title,
            username=body.username,
            password=password,
            url=body.url,
            notes=notes,
            tags=body.tags,
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
    vault.delete(entry.id)
    return {"deleted": entry.title}


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

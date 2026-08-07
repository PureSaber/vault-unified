from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from vault_unified.api.deps import get_vault
from vault_unified.api.schemas import ConflictResolveIn, SyncPreferencesIn, SyncPreferencesOut
from vault_unified.manager import UnifiedVault
from vault_unified.models import PrimarySource, SecretEntry, SyncPreferences

router = APIRouter(tags=["sync"])


@router.get("/status")
def status(vault: UnifiedVault = Depends(get_vault)) -> dict:
    return {"components": vault.status()}


@router.get("/sync/preferences", response_model=SyncPreferencesOut)
def get_preferences(vault: UnifiedVault = Depends(get_vault)) -> SyncPreferencesOut:
    prefs = vault.get_prefs()
    return SyncPreferencesOut(**prefs.to_dict())


@router.put("/sync/preferences", response_model=SyncPreferencesOut)
def update_preferences(
    body: SyncPreferencesIn,
    vault: UnifiedVault = Depends(get_vault),
) -> SyncPreferencesOut:
    prefs = vault.get_prefs()
    data = prefs.to_dict()
    for key, value in body.model_dump(exclude_none=True).items():
        data[key] = value
    if "primary" in data:
        data["primary"] = PrimarySource(data["primary"]).value
    updated = SyncPreferences.from_dict(data)
    vault.save_prefs(updated)
    return SyncPreferencesOut(**vault.get_prefs().to_dict())


@router.post("/sync")
def sync_bidirectional(vault: UnifiedVault = Depends(get_vault)) -> dict:
    result = vault.sync_bidirectional()
    return result.to_dict()


@router.post("/sync/pull/{source}")
def pull_source(source: str, vault: UnifiedVault = Depends(get_vault)) -> dict:
    from vault_unified.models import Source

    try:
        src = Source(source)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid source") from exc
    prefs = vault.get_prefs()
    if not prefs.is_source_enabled(src):
        raise HTTPException(
            status_code=400,
            detail=f"Source {source} is disabled in sync preferences",
        )
    try:
        return vault.sync.pull_source(src)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/sync/push")
def push_dirty(vault: UnifiedVault = Depends(get_vault)) -> dict:
    return vault.push_all_dirty()


@router.post("/sync/push/{entry_id}")
def push_entry(entry_id: str, vault: UnifiedVault = Depends(get_vault)) -> dict:
    try:
        return vault.push_entry(entry_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/sync/conflicts")
def list_conflicts(vault: UnifiedVault = Depends(get_vault)) -> list:
    return [c.to_dict() for c in vault.list_conflicts()]


@router.post("/sync/conflicts/{conflict_id}/resolve")
def resolve_conflict(
    conflict_id: str,
    body: ConflictResolveIn,
    vault: UnifiedVault = Depends(get_vault),
) -> dict:
    merged = None
    if body.merged:
        merged = SecretEntry.from_dict(body.merged)
    try:
        entry = vault.resolve_conflict(conflict_id, body.choice, merged)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"resolved": entry.title, "id": entry.id}

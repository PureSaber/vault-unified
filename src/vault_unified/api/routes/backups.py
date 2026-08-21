from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from vault_unified.api.deps import get_token, get_vault
from vault_unified.api.schemas import (
    BackupCreateIn,
    BackupPinIn,
    BackupPruneIn,
    BackupRestoreIn,
)
from vault_unified.backup_manager import (
    apply_retention_plan,
    create_manual_backup,
    default_backup_dir,
    list_backups,
    restore_backup,
    retention_plan,
    set_backup_pinned,
)
from vault_unified.manager import UnifiedVault
from vault_unified.session import sessions

router = APIRouter(prefix="/backups", tags=["backups"])


def _summary(vault: UnifiedVault) -> dict:
    records = list_backups(vault.vault_path, vault.local.credential)
    return {
        "backups": [record.to_dict() for record in records],
        "count": len(records),
        "total_bytes": sum(record.size for record in records),
        "verified_count": sum(1 for record in records if record.verified),
        "pinned_count": sum(1 for record in records if record.pinned),
        "default_destination": str(default_backup_dir().resolve()),
    }


@router.get("")
def get_backups(vault: UnifiedVault = Depends(get_vault)) -> dict:
    try:
        return _summary(vault)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/create")
def create_backup(
    body: BackupCreateIn,
    vault: UnifiedVault = Depends(get_vault),
) -> dict:
    try:
        record = create_manual_backup(
            vault.vault_path,
            vault.local.credential,
            body.destination_dir,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"created": record.to_dict(), **_summary(vault)}


@router.put("/pin")
def pin_backup(
    body: BackupPinIn,
    vault: UnifiedVault = Depends(get_vault),
) -> dict:
    try:
        record = set_backup_pinned(
            vault.vault_path,
            body.path,
            vault.local.credential,
            body.pinned,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"backup": record.to_dict(), **_summary(vault)}


@router.post("/prune")
def prune_backups(
    body: BackupPruneIn,
    vault: UnifiedVault = Depends(get_vault),
) -> dict:
    kwargs = {
        "newest_count": body.newest_count,
        "daily_days": body.daily_days,
        "weekly_weeks": body.weekly_weeks,
    }
    try:
        if body.apply:
            result = apply_retention_plan(
                vault.vault_path,
                vault.local.credential,
                **kwargs,
            )
        else:
            result = retention_plan(
                vault.vault_path,
                vault.local.credential,
                **kwargs,
            )
            result = {
                **result,
                "applied": False,
                "deleted_count": 0,
                "reclaimed_bytes": 0,
                "errors": [],
            }
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {**result, "summary": _summary(vault)}


@router.post("/restore")
def restore_registered_backup(
    body: BackupRestoreIn,
    token: str = Depends(get_token),
    vault: UnifiedVault = Depends(get_vault),
) -> dict:
    if not body.confirm_restore:
        raise HTTPException(
            status_code=400,
            detail="confirm_restore=true is required",
        )
    credential = body.password or vault.local.credential
    try:
        restore_backup(vault.vault_path, body.path, credential)
        # Reopen before invalidating the current session so a successful response
        # proves that the committed active bytes are readable.
        UnifiedVault(vault.vault_path, credential)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        # This is a backup credential/format failure, not an API-session failure;
        # keep the active session usable so the user can correct the old password.
        raise HTTPException(
            status_code=400,
            detail="Backup could not be authenticated or restored",
        ) from exc
    sessions.lock(token)
    return {
        "restored": body.path,
        "locked": True,
        "message": "Backup restored; unlock the vault again",
    }

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from vault_unified.api.deps import get_vault
from vault_unified.api.schemas import PersonalSettingsIn, PersonalSettingsOut
from vault_unified.manager import UnifiedVault
from vault_unified.personal_settings import (
    load_personal_settings,
    maybe_create_scheduled_backup,
    save_personal_settings,
    update_personal_settings,
)


router = APIRouter(prefix="/personal", tags=["personal"])


def _out(settings) -> PersonalSettingsOut:
    return PersonalSettingsOut(
        lock_after_seconds=settings.lock_after_seconds,
        auto_backup_enabled=settings.auto_backup_enabled,
        auto_backup_interval_hours=settings.auto_backup_interval_hours,
        auto_backup_destination=settings.auto_backup_destination,
        last_auto_backup_at=settings.last_auto_backup_at,
    )


@router.get("/settings", response_model=PersonalSettingsOut)
def get_settings(vault: UnifiedVault = Depends(get_vault)) -> PersonalSettingsOut:
    _ = vault
    try:
        return _out(load_personal_settings())
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.put("/settings", response_model=PersonalSettingsOut)
def save_settings(
    body: PersonalSettingsIn,
    vault: UnifiedVault = Depends(get_vault),
) -> PersonalSettingsOut:
    _ = vault
    try:
        current = load_personal_settings()
        saved = update_personal_settings(current, **body.model_dump())
        return _out(save_personal_settings(saved))
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/maintenance")
def run_maintenance(vault: UnifiedVault = Depends(get_vault)) -> dict:
    """Run user-owned maintenance and return deduplicable desktop notices."""
    notices: list[dict[str, str]] = []
    try:
        backup = maybe_create_scheduled_backup(vault)
        if backup:
            notices.append(
                {
                    "code": f"scheduled-backup:{backup.sha256}",
                    "level": "info",
                    "message": f"Scheduled encrypted backup created: {backup.path}",
                }
            )
    except (OSError, ValueError) as exc:
        notices.append(
            {
                "code": f"scheduled-backup-error:{type(exc).__name__}",
                "level": "error",
                "message": "Scheduled backup could not be created",
            }
        )

    components = vault.status()
    conflicts = int(components.get("conflicts", "0"))
    dirty = int(components.get("dirty", "0"))
    if conflicts:
        notices.append(
            {
                "code": f"sync-conflicts:{conflicts}",
                "level": "error",
                "message": f"{conflicts} synchronization conflict(s) need attention",
            }
        )
    elif dirty:
        notices.append(
            {
                "code": f"sync-pending:{dirty}",
                "level": "info",
                "message": f"{dirty} change(s) are waiting to sync",
            }
        )
    return {"settings": _out(load_personal_settings()).model_dump(), "components": components, "notices": notices}

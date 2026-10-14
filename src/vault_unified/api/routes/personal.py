from __future__ import annotations

from datetime import datetime, timezone
import hashlib

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, StrictBool

from vault_unified.api.deps import get_token, get_vault
from vault_unified.api.schemas import PersonalSettingsIn, PersonalSettingsOut, PayloadUpgradeIn, RestorePreviewCancelIn
from vault_unified.manager import UnifiedVault
from vault_unified.restore_preview import restore_preview_store, RestorePreviewError
from vault_unified.session import sessions
from vault_unified.personal_settings import (
    load_personal_settings,
    maybe_create_scheduled_backup,
    ScheduledBackupStatusError,
    save_backup_status,
    save_personal_settings,
    update_backup_status,
    update_personal_settings,
)


router = APIRouter(prefix="/personal", tags=["personal"])


class UpdatePrepare(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: StrictBool = False


@router.post("/update/prepare")
def prepare_desktop_update(body: UpdatePrepare, vault: UnifiedVault = Depends(get_vault),
                           token: str = Depends(get_token)) -> dict:
    if body.confirm is not True:
        raise HTTPException(400, "Confirm the desktop update")
    from vault_unified.backup_manager import create_manual_backup, set_backup_pinned
    try:
        with sessions.active(token, vault), vault.local._lock:
            backup = create_manual_backup(vault.vault_path, vault.local.credential)
            set_backup_pinned(vault.vault_path, backup.path, vault.local.credential, True)
            sessions.lock_all()
    except PermissionError:
        raise HTTPException(401, "Unlock again before updating") from None
    except (OSError, ValueError):
        raise HTTPException(409, "Could not retain the pre-update backup; installation stopped") from None
    return {"backup_path": backup.path, "locked": True}


@router.get("/format")
def payload_format(vault: UnifiedVault = Depends(get_vault)) -> dict:
    return {"version": vault.local.payload_version, "current_version": 3}


@router.post("/format/preview")
def preview_payload_upgrade(
    vault: UnifiedVault = Depends(get_vault), token: str = Depends(get_token),
) -> dict:
    if vault.local.payload_version == 3:
        raise HTTPException(status_code=409, detail="Vault format is already current")
    intent = restore_preview_store.issue(
        scope=token, kind="payload_upgrade", source_path="", source_sha256="",
        active_sha256=hashlib.sha256(vault.vault_path.read_bytes()).hexdigest(),
        active_state_digest=vault.local.state_digest(), active_generation=vault.local.generation,
    )
    return {"preview_token": intent.token, "entry_count": len(vault.local.export_payload()["entries"])}


@router.post("/format/cancel")
def cancel_payload_upgrade(body: RestorePreviewCancelIn, token: str = Depends(get_token),
                           vault: UnifiedVault = Depends(get_vault)) -> dict:
    try:
        restore_preview_store.consume(body.preview_token, scope=token, kind="payload_upgrade")
    except RestorePreviewError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"cancelled": True}


@router.post("/format/apply")
def apply_payload_upgrade(body: PayloadUpgradeIn, token: str = Depends(get_token),
                          vault: UnifiedVault = Depends(get_vault)) -> dict:
    if not body.confirm_upgrade:
        raise HTTPException(status_code=400, detail="Upgrade confirmation is required")
    try:
        intent = restore_preview_store.consume(body.preview_token, scope=token, kind="payload_upgrade")
        if vault.local.state_digest() != intent.active_state_digest:
            raise ValueError("Vault changed after the upgrade preview")
        backup = vault.local.upgrade_payload(
            expected_generation=intent.active_generation, expected_sha256=intent.active_sha256,
        )
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    finally:
        # All sessions must reload, including sessions holding the previous schema.
        if vault.local.payload_version == 3:
            sessions.lock_all()
    return {"version": 3, "backup_path": backup, "locked": True}


def _out(settings) -> PersonalSettingsOut:
    return PersonalSettingsOut(
        lock_after_seconds=settings.lock_after_seconds,
        auto_backup_enabled=settings.auto_backup_enabled,
        auto_backup_interval_hours=settings.auto_backup_interval_hours,
        auto_backup_destination=settings.auto_backup_destination,
        last_auto_backup_at=settings.last_auto_backup_at,
        backup_status=settings.backup_status,
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
    from vault_unified.organization import purge_expired
    try:
        purge_expired(vault)
    except (OSError, ValueError):
        notices.append({"code": "trash-cleanup-failed", "level": "error", "message": "Trash cleanup failed; retry after reopening the vault"})
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
    except ScheduledBackupStatusError:
        try:
            settings = load_personal_settings()
            update_backup_status(
                settings,
                last_error_at=datetime.now(timezone.utc).isoformat(),
                last_error_summary="Encrypted backup was created, but its schedule status could not be saved",
            )
            save_backup_status(settings.backup_status)
        except (OSError, ValueError):
            pass
        notices.append(
            {
                "code": "scheduled-backup-status-error",
                "level": "error",
                "message": "Encrypted backup was created, but its schedule status could not be saved",
            }
        )
    except (OSError, ValueError) as exc:
        try:
            settings = load_personal_settings()
            update_backup_status(
                settings,
                last_error_at=datetime.now(timezone.utc).isoformat(),
                last_error_summary="Automatic encrypted backup could not be created",
            )
            save_backup_status(settings.backup_status)
        except (OSError, ValueError):
            pass
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

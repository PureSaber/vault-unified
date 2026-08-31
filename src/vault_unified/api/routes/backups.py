from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException

from vault_unified.api.deps import get_token, get_vault
from vault_unified.api.schemas import (
    BackupCreateIn,
    BackupDestinationTestIn,
    BackupPinIn,
    BackupPruneIn,
    BackupRestoreApplyIn,
    BackupRestoreIn,
    BackupRestorePreviewIn,
    BackupVerifyIn,
    RestorePreviewCancelIn,
)
from vault_unified.backup_manager import (
    BackupRecord,
    apply_retention_plan,
    create_manual_backup,
    default_backup_dir,
    list_backups,
    restore_backup,
    retention_plan,
    set_backup_pinned,
    test_backup_destination,
    verify_backup,
)
from vault_unified.backup_preview import (
    BackupPreviewExpired,
    BackupPreviewSessionMismatch,
    backup_preview_store,
)
from vault_unified.manager import UnifiedVault
from vault_unified.personal_settings import (
    BackupStatus,
    load_personal_settings,
    save_backup_status,
    update_backup_status,
)
from vault_unified.restore_preview import (
    RestorePreviewExpired,
    RestorePreviewScopeMismatch,
    restore_preview_store,
)
from vault_unified.session import sessions

router = APIRouter(prefix="/backups", tags=["backups"])


def _summary(vault: UnifiedVault) -> dict:
    records = list_backups(vault.vault_path, vault.local.credential)
    settings = load_personal_settings()
    stored = BackupStatus.from_dict(settings.backup_status)
    latest_verified = next((record for record in records if record.verified), None)
    last_success = stored.last_success_at or (
        latest_verified.modified_at if latest_verified else ""
    )
    next_eligible = ""
    if settings.auto_backup_enabled:
        if settings.last_auto_backup_at:
            next_eligible = (
                datetime.fromisoformat(settings.last_auto_backup_at)
                + timedelta(hours=settings.auto_backup_interval_hours)
            ).isoformat()
        else:
            next_eligible = datetime.now(timezone.utc).isoformat()
    return {
        "backups": [record.to_dict() for record in records],
        "count": len(records),
        "total_bytes": sum(record.size for record in records),
        "verified_count": sum(1 for record in records if record.verified),
        "pinned_count": sum(1 for record in records if record.pinned),
        "default_destination": str(default_backup_dir().resolve()),
        "health": {
            **stored.to_dict(),
            "last_success_at": last_success,
            "backup_location": settings.auto_backup_destination,
            "next_eligible_at": next_eligible,
            "auto_backup_enabled": settings.auto_backup_enabled,
        },
    }


def _fallback_summary_after_created_backup(
    vault: UnifiedVault,
    created: BackupRecord,
) -> dict:
    """Preserve an explicit successful response if health metadata is unavailable."""

    try:
        records = list_backups(vault.vault_path, vault.local.credential)
    except (OSError, ValueError):
        records = [created]
    latest_verified = next((record for record in records if record.verified), None)
    return {
        "backups": [record.to_dict() for record in records],
        "count": len(records),
        "total_bytes": sum(record.size for record in records),
        "verified_count": sum(1 for record in records if record.verified),
        "pinned_count": sum(1 for record in records if record.pinned),
        "default_destination": str(default_backup_dir().resolve()),
        "health": {
            **BackupStatus().to_dict(),
            "last_success_at": latest_verified.modified_at if latest_verified else "",
            "backup_location": "",
            "next_eligible_at": "",
            "auto_backup_enabled": False,
        },
    }


def _save_success_status(completed_at: str) -> str:
    """Return a warning if health metadata could not be saved after success."""

    try:
        settings = load_personal_settings()
        update_backup_status(
            settings,
            last_success_at=completed_at,
            last_error_at="",
            last_error_summary="",
        )
        save_backup_status(settings.backup_status)
        return ""
    except (OSError, ValueError):
        return "Backup was created and verified, but its health status could not be saved"


def _save_error_status(summary: str) -> None:
    try:
        settings = load_personal_settings()
        update_backup_status(
            settings,
            last_error_at=datetime.now(timezone.utc).isoformat(),
            last_error_summary=summary,
        )
        save_backup_status(settings.backup_status)
    except (OSError, ValueError):
        # The primary operation still returns an error. Never replace it with a
        # second metadata error or expose exception details.
        pass


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
        _save_error_status("The backup source or destination was not found")
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (OSError, ValueError) as exc:
        _save_error_status("The encrypted backup could not be created")
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    warning = _save_success_status(record.modified_at)
    try:
        summary = _summary(vault)
    except (OSError, ValueError):
        warning = warning or "Backup was created and verified, but the updated backup summary could not be loaded"
        summary = _fallback_summary_after_created_backup(vault, record)
    return {"created": record.to_dict(), "warning": warning, **summary}


@router.post("/test-destination")
def test_destination(
    body: BackupDestinationTestIn,
    vault: UnifiedVault = Depends(get_vault),
) -> dict:
    _ = vault
    try:
        return test_backup_destination(body.destination_dir)
    except OSError as exc:
        raise HTTPException(
            status_code=400,
            detail="Backup folder could not be inspected",
        ) from exc


@router.post("/verify")
def verify_registered_backup(
    body: BackupVerifyIn,
    vault: UnifiedVault = Depends(get_vault),
) -> dict:
    records = list_backups(vault.vault_path, vault.local.credential)
    selected = body.path or (records[0].path if records else "")
    if not selected:
        raise HTTPException(status_code=404, detail="No backup is available to verify")
    checked_at = datetime.now(timezone.utc).isoformat()
    try:
        record = verify_backup(vault.vault_path, selected, vault.local.credential)
    except (KeyError, FileNotFoundError) as exc:
        saved = _record_verification_failure(checked_at)
        detail = "Backup was not found"
        if not saved:
            detail += "; the failed verification status could not be saved"
        raise HTTPException(status_code=404, detail=detail) from exc
    except Exception as exc:
        saved = _record_verification_failure(checked_at)
        detail = "Backup authentication or parsing failed; the active vault was not changed"
        if not saved:
            detail += "; the failed verification status could not be saved"
        raise HTTPException(status_code=400, detail=detail) from exc
    warning = ""
    try:
        settings = load_personal_settings()
        update_backup_status(
            settings,
            last_verification_at=checked_at,
            last_verification_status="passed",
        )
        save_backup_status(settings.backup_status)
    except (OSError, ValueError):
        warning = "Backup passed verification, but its verification status could not be saved"
    return {
        "verified": True,
        "verified_at": checked_at,
        "backup": record.to_dict(),
        "message": "Backup authentication and parsing passed; the active vault was not changed",
        "warning": warning,
    }


def _record_verification_failure(checked_at: str) -> bool:
    try:
        settings = load_personal_settings()
        update_backup_status(
            settings,
            last_verification_at=checked_at,
            last_verification_status="failed",
        )
        save_backup_status(settings.backup_status)
        return True
    except (OSError, ValueError):
        return False


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
    token: str = Depends(get_token),
    vault: UnifiedVault = Depends(get_vault),
) -> dict:
    kwargs = {
        "newest_count": body.newest_count,
        "daily_days": body.daily_days,
        "weekly_weeks": body.weekly_weeks,
    }
    policy = (
        body.newest_count,
        body.daily_days,
        body.weekly_weeks,
    )
    try:
        if body.apply:
            if not body.preview_token:
                raise HTTPException(
                    status_code=409,
                    detail="A fresh backup cleanup preview token is required",
                )
            try:
                intent = backup_preview_store.consume(
                    body.preview_token,
                    session_token=token,
                )
            except (BackupPreviewExpired, BackupPreviewSessionMismatch) as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            if intent.policy != policy:
                raise HTTPException(
                    status_code=409,
                    detail="Backup cleanup policy changed; create a new preview",
                )
            result = apply_retention_plan(
                vault.vault_path,
                vault.local.credential,
                approved_plan=intent.plan,
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
            intent = backup_preview_store.issue(
                session_token=token,
                policy=policy,
                plan=result,
            )
            result = {
                **result,
                "preview_token": intent.token,
                "expires_at": datetime.fromtimestamp(
                    intent.expires_at,
                    tz=timezone.utc,
                ).isoformat(),
            }
    except HTTPException:
        raise
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {**result, "summary": _summary(vault)}


@router.post("/restore")
def restore_registered_backup(
    body: BackupRestoreIn,
    token: str = Depends(get_token),
    vault: UnifiedVault = Depends(get_vault),
) -> dict:
    _ = (body, token, vault)
    raise HTTPException(
        status_code=409,
        detail="A fresh restore preview is required before applying a backup",
    )


@router.post("/restore/preview")
def preview_registered_backup_restore(
    body: BackupRestorePreviewIn,
    token: str = Depends(get_token),
    vault: UnifiedVault = Depends(get_vault),
) -> dict:
    credential = body.password or vault.local.credential
    try:
        record = verify_backup(vault.vault_path, body.path, credential)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail="Backup could not be authenticated or parsed; no data was changed",
        ) from exc
    active_sha256 = hashlib.sha256(vault.vault_path.read_bytes()).hexdigest()
    intent = restore_preview_store.issue(
        scope=token,
        kind="backup",
        source_path=record.path,
        source_sha256=record.sha256,
        active_sha256=active_sha256,
        active_state_digest=vault.local.state_digest(),
        active_generation=vault.local.generation,
    )
    return {
        "preview_token": intent.token,
        "expires_at": datetime.fromtimestamp(intent.expires_at, tz=timezone.utc).isoformat(),
        "backup": record.to_dict(),
        "impact": "The active vault will be atomically replaced, retained as an encrypted recovery copy, and then locked",
        "warning": "Preview only: the active vault was not changed",
    }


@router.post("/restore/apply")
def apply_registered_backup_restore(
    body: BackupRestoreApplyIn,
    token: str = Depends(get_token),
    vault: UnifiedVault = Depends(get_vault),
) -> dict:
    if not body.confirm_restore:
        raise HTTPException(status_code=400, detail="Restore confirmation is required")
    try:
        intent = restore_preview_store.consume(
            body.preview_token,
            scope=token,
            kind="backup",
        )
    except (RestorePreviewExpired, RestorePreviewScopeMismatch) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    current_sha256 = hashlib.sha256(vault.vault_path.read_bytes()).hexdigest()
    if (
        current_sha256 != intent.active_sha256
        or vault.local.state_digest() != intent.active_state_digest
        or vault.local.generation != intent.active_generation
    ):
        raise HTTPException(
            status_code=409,
            detail="The vault changed after the restore preview; create a new preview",
        )
    credential = body.password or vault.local.credential
    try:
        restore_backup(
            vault.vault_path,
            intent.source_path,
            credential,
            expected_active_sha256=intent.active_sha256,
            expected_backup_sha256=intent.source_sha256,
        )
        UnifiedVault(vault.vault_path, credential)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail="Backup restore failed; the previous active vault remains available",
        ) from exc
    sessions.lock(token)
    restore_preview_store.clear_scope(token)
    return {
        "restored": intent.source_path,
        "locked": True,
        "message": "Backup restored; unlock the vault again",
    }


@router.post("/restore/cancel")
def cancel_registered_backup_restore(
    body: RestorePreviewCancelIn,
    token: str = Depends(get_token),
    vault: UnifiedVault = Depends(get_vault),
) -> dict:
    _ = vault
    try:
        restore_preview_store.consume(
            body.preview_token,
            scope=token,
            kind="backup",
        )
    except (RestorePreviewExpired, RestorePreviewScopeMismatch) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"cancelled": True}

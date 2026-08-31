from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request

from vault_unified.config import get_vault_path
from vault_unified.api.deps import get_token, require_loopback
from vault_unified.api.schemas import (
    CreateVaultRequest,
    EmergencyRecoveryApplyIn,
    EmergencyRecoveryIn,
    EmergencyRecoveryPreviewIn,
    RecoveryKitCreateIn,
    RestoreVaultApplyIn,
    RestoreVaultRequest,
    RestorePreviewCancelIn,
    UnlockRequest,
    UnlockResponse,
    VaultInfoOut,
)
from vault_unified.session import sessions
from vault_unified.personal_settings import (
    load_personal_settings,
    save_backup_status,
    update_backup_status,
)
from vault_unified.recovery_kit import (
    create_recovery_kit,
    generate_recovery_code,
    inspect_recovery_kit,
    restore_from_recovery_kit,
)
from vault_unified.crypto import decrypt_payload
from vault_unified.models import SecretEntry
from vault_unified.restore_preview import (
    RestorePreviewExpired,
    RestorePreviewScopeMismatch,
    restore_preview_store,
)
from vault_unified.storage import RecoveryRequiredError
from vault_unified.vault_format import (
    V3Container,
    inspect_vault_format_file,
    is_framed_vault_file,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _require_desktop(request: Request) -> None:
    require_loopback(request)
    if request.headers.get("x-vault-client", "") != "vault-unified-desktop":
        raise HTTPException(status_code=403, detail="Desktop client required")


@router.get("/vault-info", response_model=VaultInfoOut)
def vault_info(request: Request) -> VaultInfoOut:
    require_loopback(request)
    path = get_vault_path()
    if not path.exists():
        return VaultInfoOut(exists=False, format="missing", path=str(path.resolve()))
    try:
        container = inspect_vault_format_file(path)
    except Exception:
        return VaultInfoOut(exists=True, format="unreadable", path=str(path.resolve()))
    vault_format = "v3" if isinstance(container, V3Container) else "legacy"
    return VaultInfoOut(exists=True, format=vault_format, path=str(path.resolve()))


@router.post("/create", response_model=UnlockResponse)
def create_vault(body: CreateVaultRequest, request: Request) -> UnlockResponse:
    _require_desktop(request)
    try:
        token, _ = sessions.create_v3(
            body.password,
            body.confirm_password,
            remember=body.remember,
        )
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RecoveryRequiredError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return UnlockResponse(token=token, message="created")


@router.post("/restore", response_model=UnlockResponse)
def restore_vault(body: RestoreVaultRequest, request: Request) -> UnlockResponse:
    _require_desktop(request)
    _ = body
    raise HTTPException(
        status_code=409,
        detail="A fresh backup preview is required before restoring",
    )


@router.post("/restore/preview")
def preview_vault_restore(body: RestoreVaultRequest, request: Request) -> dict:
    _require_desktop(request)
    source = Path(body.backup_path).expanduser().resolve()
    target = get_vault_path().expanduser().resolve()
    if target.exists():
        raise HTTPException(status_code=409, detail="An active vault already exists")
    if source == target:
        raise HTTPException(status_code=400, detail="Backup path must differ from the active vault")
    try:
        if source.is_symlink() or not source.is_file():
            raise FileNotFoundError("Backup file was not found")
        source_bytes = source.read_bytes()
        payload = decrypt_payload(body.password, source_bytes)
        if not isinstance(payload, dict) or not isinstance(payload.get("entries"), dict):
            raise ValueError("Backup payload is invalid")
        for entry_id, entry in payload["entries"].items():
            if not isinstance(entry_id, str) or not isinstance(entry, dict):
                raise ValueError("Backup entry schema is invalid")
            SecretEntry.from_dict(entry)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=400, detail="Backup file could not be read") from exc
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid password or backup vault") from exc
    stat = source.stat()
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    intent = restore_preview_store.issue(
        scope=request.app.state.instance_id,
        kind="startup_backup",
        source_path=str(source),
        source_sha256=source_sha256,
        active_sha256="",
        active_state_digest="",
        active_generation=-1,
    )
    return {
        "preview_token": intent.token,
        "expires_at": datetime.fromtimestamp(intent.expires_at, tz=timezone.utc).isoformat(),
        "backup": {
            "path": str(source),
            "size": len(source_bytes),
            "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            "sha256": source_sha256,
        },
        "impact": "A new active vault will be created from this encrypted backup",
        "warning": "Preview only: no active vault was created",
    }


@router.post("/restore/apply")
def apply_vault_restore(body: RestoreVaultApplyIn, request: Request) -> dict:
    _require_desktop(request)
    if not body.confirm_restore:
        raise HTTPException(status_code=400, detail="Restore confirmation is required")
    try:
        intent = restore_preview_store.consume(
            body.preview_token,
            scope=request.app.state.instance_id,
            kind="startup_backup",
        )
    except (RestorePreviewExpired, RestorePreviewScopeMismatch) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if get_vault_path().exists():
        raise HTTPException(status_code=409, detail="Vault state changed after the preview")
    try:
        token, _ = sessions.restore(
            intent.source_path,
            body.password,
            remember=body.remember,
            expected_source_sha256=intent.source_sha256,
        )
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RecoveryRequiredError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=400, detail="Backup file could not be read") from exc
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid password or changed backup vault") from exc
    sessions.lock(token)
    restore_preview_store.clear_scope(request.app.state.instance_id)
    return {"locked": True, "message": "Backup restored; unlock the vault again"}


@router.post("/restore/cancel")
def cancel_vault_restore(body: RestorePreviewCancelIn, request: Request) -> dict:
    _require_desktop(request)
    try:
        restore_preview_store.consume(
            body.preview_token,
            scope=request.app.state.instance_id,
            kind="startup_backup",
        )
    except (RestorePreviewExpired, RestorePreviewScopeMismatch) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"cancelled": True}


@router.post("/recovery-code")
def new_recovery_code(token: str = Depends(get_token)) -> dict:
    # Require an existing unlocked vault before showing a high-value recovery
    # code in the renderer.  The value is never persisted by the application.
    try:
        sessions.get(token)
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return {"recovery_code": generate_recovery_code()}


@router.post("/recovery-kit")
def create_emergency_recovery_kit(
    body: RecoveryKitCreateIn,
    token: str = Depends(get_token),
) -> dict:
    if body.recovery_code != body.confirm_recovery_code:
        raise HTTPException(status_code=400, detail="Recovery code confirmation does not match")
    try:
        vault = sessions.get(token)
        path = create_recovery_kit(vault, body.recovery_code, body.destination_dir)
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    warning = ""
    try:
        settings = load_personal_settings()
        update_backup_status(
            settings,
            recovery_kit_created_at=datetime.now(timezone.utc).isoformat(),
        )
        save_backup_status(settings.backup_status)
    except (OSError, ValueError):
        warning = "Recovery kit was created, but its status could not be saved"
    return {
        "path": str(path),
        "message": "Recovery kit created. Store this encrypted file separately from the recovery code.",
        "warning": warning,
    }


@router.post("/recover", response_model=UnlockResponse)
def emergency_recover(body: EmergencyRecoveryIn, request: Request) -> UnlockResponse:
    _require_desktop(request)
    _ = body
    raise HTTPException(
        status_code=409,
        detail="A fresh recovery-kit preview is required before restoring",
    )


@router.post("/recover/preview")
def preview_emergency_recovery(body: EmergencyRecoveryPreviewIn, request: Request) -> dict:
    _require_desktop(request)
    target = get_vault_path().expanduser().resolve()
    try:
        kit = inspect_recovery_kit(body.kit_path, body.recovery_code)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Recovery kit could not be authenticated or parsed") from exc
    active_sha256 = hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else ""
    intent = restore_preview_store.issue(
        scope=request.app.state.instance_id,
        kind="recovery_kit",
        source_path=kit["path"],
        source_sha256=kit["sha256"],
        active_sha256=active_sha256,
        active_state_digest="",
        active_generation=-1,
    )
    return {
        "preview_token": intent.token,
        "expires_at": datetime.fromtimestamp(intent.expires_at, tz=timezone.utc).isoformat(),
        "kit": kit,
        "impact": "The active vault will be atomically replaced, retained as an encrypted recovery copy, and protected with the new master password",
        "warning": "Preview only: the active vault was not changed",
    }


@router.post("/recover/apply")
def apply_emergency_recovery(body: EmergencyRecoveryApplyIn, request: Request) -> dict:
    _require_desktop(request)
    if not body.confirm_recovery:
        raise HTTPException(status_code=400, detail="Recovery confirmation is required")
    if body.new_password != body.confirm_new_password:
        raise HTTPException(status_code=400, detail="New master password confirmation does not match")
    try:
        intent = restore_preview_store.consume(
            body.preview_token,
            scope=request.app.state.instance_id,
            kind="recovery_kit",
        )
    except (RestorePreviewExpired, RestorePreviewScopeMismatch) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    target = get_vault_path().expanduser().resolve()
    active_sha256 = hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else ""
    if active_sha256 != intent.active_sha256:
        raise HTTPException(status_code=409, detail="Vault state changed after the recovery preview")
    try:
        restore_from_recovery_kit(
            target,
            intent.source_path,
            body.recovery_code,
            body.new_password,
            expected_target_sha256=intent.active_sha256,
            expected_kit_sha256=intent.source_sha256,
        )
        sessions.lock_all()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Recovery failed; the previous active vault remains available") from exc
    restore_preview_store.clear_scope(request.app.state.instance_id)
    return {"locked": True, "message": "Recovery completed; unlock the vault again"}


@router.post("/recover/cancel")
def cancel_emergency_recovery(body: RestorePreviewCancelIn, request: Request) -> dict:
    _require_desktop(request)
    try:
        restore_preview_store.consume(
            body.preview_token,
            scope=request.app.state.instance_id,
            kind="recovery_kit",
        )
    except (RestorePreviewExpired, RestorePreviewScopeMismatch) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"cancelled": True}


@router.post("/unlock", response_model=UnlockResponse)
def unlock(body: UnlockRequest, request: Request) -> UnlockResponse:
    require_loopback(request)
    try:
        token, _ = sessions.unlock(body.password, remember=body.remember)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RecoveryRequiredError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid password or vault") from exc
    return UnlockResponse(token=token)


@router.post("/lock")
def lock(token: str = Depends(get_token)) -> dict:
    from vault_unified.import_flow import import_flow_store
    from vault_unified.restore_preview import restore_preview_store

    import_flow_store.clear_session(token)
    restore_preview_store.clear_scope(token)
    sessions.lock(token)
    return {"message": "locked"}


@router.get("/status")
def auth_status(token: str = Depends(get_token)) -> dict:
    return {"unlocked": sessions.is_unlocked(token)}


@router.get("/check-keyring")
def check_keyring(request: Request) -> dict:
    require_loopback(request)
    path = get_vault_path()
    if not path.exists():
        return {"has_saved_password": False}
    if is_framed_vault_file(path):
        from vault_unified.device_keyring import device_unlock_available

        return {"has_saved_password": device_unlock_available(path)}
    from vault_unified.keyring_store import get_master_password

    pwd = get_master_password()
    return {"has_saved_password": pwd is not None}


@router.post("/unlock-keyring", response_model=UnlockResponse)
def unlock_keyring(request: Request) -> UnlockResponse:
    """Unlock using Windows Credential Manager. Loopback + desktop client header required."""
    _require_desktop(request)
    try:
        token, _ = sessions.unlock()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RecoveryRequiredError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return UnlockResponse(token=token)

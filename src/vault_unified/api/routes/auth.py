from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from vault_unified.config import get_vault_path
from vault_unified.api.deps import get_token, require_loopback
from vault_unified.api.schemas import (
    CreateVaultRequest,
    RestoreVaultRequest,
    UnlockRequest,
    UnlockResponse,
    VaultInfoOut,
)
from vault_unified.session import sessions
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
    try:
        token, _ = sessions.restore(
            body.backup_path,
            body.password,
            remember=body.remember,
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
        raise HTTPException(status_code=401, detail="Invalid password or backup vault") from exc
    return UnlockResponse(token=token, message="restored")


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

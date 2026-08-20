from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from vault_unified.api.deps import get_token, get_vault, require_loopback
from vault_unified.api.schemas import UnlockRequest, UnlockResponse
from vault_unified.session import sessions
from vault_unified.storage import RecoveryRequiredError

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/unlock", response_model=UnlockResponse)
def unlock(body: UnlockRequest, request: Request) -> UnlockResponse:
    require_loopback(request)
    try:
        token, _ = sessions.unlock(body.password, remember=body.remember)
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
    from vault_unified.keyring_store import get_master_password

    pwd = get_master_password()
    return {"has_saved_password": pwd is not None}


@router.post("/unlock-keyring", response_model=UnlockResponse)
def unlock_keyring(request: Request) -> UnlockResponse:
    """Unlock using Windows Credential Manager. Loopback + desktop client header required."""
    require_loopback(request)
    client = request.headers.get("x-vault-client", "")
    if client != "vault-unified-desktop":
        raise HTTPException(status_code=403, detail="Desktop client required")
    try:
        token, _ = sessions.unlock()
    except RecoveryRequiredError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return UnlockResponse(token=token)

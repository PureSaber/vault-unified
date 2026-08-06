from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from vault_unified.api.deps import get_token, get_vault
from vault_unified.api.schemas import UnlockRequest, UnlockResponse
from vault_unified.crypto import mask_secret
from vault_unified.manager import UnifiedVault
from vault_unified.session import sessions

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/unlock", response_model=UnlockResponse)
def unlock(body: UnlockRequest) -> UnlockResponse:
    try:
        token, _ = sessions.unlock(body.password, remember=body.remember)
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
def check_keyring() -> dict:
    from vault_unified.keyring_store import get_master_password

    pwd = get_master_password()
    return {"has_saved_password": pwd is not None}


@router.post("/unlock-keyring", response_model=UnlockResponse)
def unlock_keyring() -> UnlockResponse:
    try:
        token, _ = sessions.unlock()
    except Exception as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return UnlockResponse(token=token)

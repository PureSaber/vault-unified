from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, StrictBool

from vault_unified.api.deps import get_token, get_vault
from vault_unified.manager import UnifiedVault
from vault_unified.organization import is_fillable
from vault_unified.password_health import ExposureUnavailable, exposure_count, report, login_entries
from vault_unified.personal_data import data_for
from vault_unified.session import sessions

router = APIRouter(prefix="/security", tags=["security"])


@router.get("/password-health")
def password_health(response: Response, token: str = Depends(get_token), vault: UnifiedVault = Depends(get_vault)) -> dict:
    response.headers["Cache-Control"] = "no-store"
    result = report(vault)
    try:
        sessions.get(token, touch=False)
    except PermissionError:
        raise HTTPException(status_code=401, detail="Unlock the vault again") from None
    return result


class ExposureIn(BaseModel):
    entry_id: UUID
    confirm_network: StrictBool = False


@router.post("/exposure")
def check_exposure(body: ExposureIn, response: Response, token: str = Depends(get_token), vault: UnifiedVault = Depends(get_vault)) -> dict:
    response.headers["Cache-Control"] = "no-store"
    if not body.confirm_network:
        raise HTTPException(status_code=400, detail="Enable the optional network check first")
    entry = vault.local.get(str(body.entry_id))
    if entry is None or not is_fillable(entry) or data_for(entry)["entry_type"] != "login" or not entry.password:
        raise HTTPException(status_code=400, detail="Choose an active login with a password")
    password = entry.password
    try:
        count = exposure_count(password)
    except ExposureUnavailable:
        raise HTTPException(status_code=503, detail="Exposure check unavailable; try again later") from None
    try:
        sessions.get(token, touch=False)
    except PermissionError:
        raise HTTPException(status_code=401, detail="Unlock the vault again") from None
    current = vault.local.get(entry.id)
    if current is None or not is_fillable(current) or current.password != password:
        raise HTTPException(status_code=409, detail="Login changed during the check; refresh and retry")
    return {"entry_id": entry.id, "count": count, "matching_entry_ids": [item.id for item in login_entries(vault) if item.password == password]}

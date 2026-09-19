from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from vault_unified.api.deps import get_token
from vault_unified.api.schemas import (
    BrowserFillIn, BrowserPairIn, BrowserSaveIn, BrowserSaveApplyIn, BrowserSaveCancelIn,
)
from vault_unified.browser_pairing import (
    BrowserPairingError,
    BrowserLockedError,
    browser_pairings,
    matches_for_url,
)
from vault_unified.session import sessions
from vault_unified.browser_save import BrowserSaveError, browser_saves
from vault_unified.generator import generate_password
from vault_unified.local_store import EntryTransactionConflict


router = APIRouter(prefix="/browser", tags=["browser"])


def _origin(request: Request) -> str:
    return request.headers.get("origin", "")


def _vault_for_browser(
    request: Request,
    browser_token: str | None = Header(default=None, alias="X-Vault-Browser-Token"),
):
    if not browser_token:
        raise HTTPException(status_code=401, detail="Missing browser pairing token")
    try:
        return browser_pairings.vault_for(
            browser_token, _origin(request), touch=request.url.path != "/api/browser/status",
        )
    except BrowserPairingError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@router.post("/pairing-code")
def create_pairing_code(token: str = Depends(get_token)) -> dict:
    try:
        sessions.get(token)
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return {
        "pairing_code": browser_pairings.issue(token),
        "expires_in_seconds": 300,
        "message": "Enter this one-time code in the Chromium extension within five minutes.",
    }


@router.post("/pairing/cancel")
def cancel_pairing(token: str = Depends(get_token)) -> dict:
    browser_pairings.cancel_session(token)
    return {"cancelled": True}


@router.post("/pair")
def pair_browser(
    body: BrowserPairIn,
    request: Request,
    pairing_code: str | None = Header(default=None, alias="X-Vault-Browser-Pairing"),
) -> dict:
    if not pairing_code:
        raise HTTPException(status_code=401, detail="Missing browser pairing code")
    try:
        result = browser_pairings.pair(pairing_code, _origin(request), remember=body.remember_connection)
    except BrowserPairingError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return result


@router.post("/resume")
def resume_browser(request: Request, connection_key: str = Header(alias="X-Vault-Browser-Connection")) -> dict:
    try:
        return browser_pairings.resume(connection_key, _origin(request))
    except BrowserLockedError as exc:
        raise HTTPException(status_code=423, detail=str(exc)) from exc
    except BrowserPairingError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@router.post("/disconnect")
def disconnect_browser(
    request: Request,
    connection_key: str | None = Header(default=None, alias="X-Vault-Browser-Connection"),
    browser_token: str | None = Header(default=None, alias="X-Vault-Browser-Token"),
) -> dict:
    try:
        if connection_key:
            browser_pairings.disconnect(connection_key, _origin(request))
        elif browser_token:
            browser_pairings.disconnect_token(browser_token, _origin(request))
        else:
            raise BrowserPairingError("Missing browser connection")
    except BrowserPairingError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return {"disconnected": True}


@router.post("/status")
def browser_status(vault=Depends(_vault_for_browser)) -> dict:
    return {"unlocked": True}


@router.post("/generate")
def browser_generate(vault=Depends(_vault_for_browser)) -> dict:
    return {"password": generate_password(24)}


def _save_error(exc: Exception) -> HTTPException:
    if isinstance(exc, EntryTransactionConflict):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, (BrowserSaveError, BrowserPairingError)):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail="Invalid account details")
    return HTTPException(status_code=500, detail="Account was not saved; try again")


@router.post("/save/preview")
def preview_browser_save(body: BrowserSaveIn, request: Request, vault=Depends(_vault_for_browser)) -> dict:
    try:
        return browser_saves.preview(vault, request.headers["x-vault-browser-token"], body.model_dump())
    except Exception as exc:
        raise _save_error(exc) from exc


@router.post("/save/apply")
def apply_browser_save(body: BrowserSaveApplyIn, request: Request, vault=Depends(_vault_for_browser)) -> dict:
    try:
        return browser_saves.apply(
            vault, request.headers["x-vault-browser-token"], body.preview_token,
            body.model_dump(exclude={"preview_token", "confirm_save"}), confirmed=body.confirm_save,
        )
    except Exception as exc:
        raise _save_error(exc) from exc


@router.post("/save/cancel")
def cancel_browser_save(body: BrowserSaveCancelIn, request: Request, vault=Depends(_vault_for_browser)) -> dict:
    browser_saves.cancel(request.headers["x-vault-browser-token"], body.preview_token)
    return {"cancelled": True}


@router.get("/matches")
@router.post("/matches")
def browser_matches(
    url: str,
    vault=Depends(_vault_for_browser),
) -> dict:
    try:
        return {"matches": matches_for_url(vault, url)}
    except BrowserPairingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/fill")
def browser_fill(
    body: BrowserFillIn,
    vault=Depends(_vault_for_browser),
) -> dict:
    try:
        allowed = {item["id"] for item in matches_for_url(vault, body.url)}
        if body.entry_id not in allowed:
            raise BrowserPairingError("The requested entry does not match this page")
        entry = vault.resolve(body.entry_id)
    except (KeyError, ValueError, BrowserPairingError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"username": entry.username, "password": entry.password}

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from vault_unified.api.deps import get_token
from vault_unified.api.schemas import BrowserFillIn
from vault_unified.browser_pairing import (
    BrowserPairingError,
    browser_pairings,
    matches_for_url,
)
from vault_unified.session import sessions


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
        return browser_pairings.vault_for(browser_token, _origin(request))
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
    request: Request,
    pairing_code: str | None = Header(default=None, alias="X-Vault-Browser-Pairing"),
) -> dict:
    if not pairing_code:
        raise HTTPException(status_code=401, detail="Missing browser pairing code")
    try:
        browser_token = browser_pairings.exchange(pairing_code, _origin(request))
    except BrowserPairingError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return {"browser_token": browser_token, "expires_in_seconds": 43_200}


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

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from vault_unified.personal_data import data_for
from vault_unified.totp import current_totp

from vault_unified.api.deps import get_token
from vault_unified.api.schemas import (
    BrowserFillIn, BrowserPairIn, BrowserSaveIn, BrowserSaveApplyIn, BrowserSaveCancelIn,
    BrowserChallengeIn, BrowserProofIn,
)
from vault_unified.browser_trust import browser_trust, BrowserTrustError, BrowserTrustUnavailable
from vault_unified import browser_discovery
from vault_unified.browser_pairing import (
    BrowserPairingError,
    BrowserLockedError,
    browser_pairings,
    matches_for_url,
)
from vault_unified.session import sessions
from vault_unified.browser_connect import BrowserConnectError, browser_connects
from vault_unified.browser_save import BrowserSaveError, browser_saves
from vault_unified.generation_history import generate_saved
from pydantic import BaseModel, Field
import hmac
from uuid import UUID
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
        result = browser_pairings.pair(pairing_code, _origin(request), remember=body.remember_connection,
                                      public_key=body.public_key, device_name=body.device_name)
    except BrowserTrustError as exc:
        raise _trust_error(exc) from exc
    except BrowserPairingError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    result["discovery_available"] = browser_discovery.register(_origin(request))
    return result


def _trust_error(exc: BrowserTrustError) -> HTTPException:
    return HTTPException(status_code=503 if isinstance(exc, BrowserTrustUnavailable) else 401,
                         detail=str(exc))


@router.get("/devices")
def trusted_devices(token: str = Depends(get_token)) -> dict:
    try:
        binding = sessions.browser_binding(token)
        return {"available": True, "devices": browser_trust.list_for(binding)}
    except BrowserTrustUnavailable:
        return {"available": False, "devices": []}
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail="Desktop vault is locked") from exc


@router.delete("/devices/{device_id}")
def revoke_browser_device(device_id: str, token: str = Depends(get_token)) -> dict:
    try:
        binding = sessions.browser_binding(token)
        if binding is None:
            raise BrowserTrustError("Device authorization requires a v3 vault")
        browser_trust.revoke(binding, device_id)
    except BrowserTrustError as exc:
        raise _trust_error(exc) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail="Desktop vault is locked") from exc
    return {"revoked": True}


@router.post("/device/challenge")
def browser_device_challenge(body: BrowserChallengeIn, request: Request) -> dict:
    try:
        record = browser_trust.load(body.device_id, _origin(request))
        if body.action == "resume":
            sessions.browser_session(tuple(record["binding"]))
        return browser_trust.challenge(body.device_id, _origin(request), body.action)
    except BrowserTrustError as exc:
        raise _trust_error(exc) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=423, detail="Desktop vault is locked") from exc


@router.post("/device/prove")
def browser_device_proof(body: BrowserProofIn, request: Request) -> dict:
    try:
        if body.action == "resume":
            return browser_pairings.trusted_resume(body.device_id, _origin(request), body.challenge_id, body.signature)
        record = browser_trust.verify(body.device_id, _origin(request), "revoke", body.challenge_id, body.signature)
        browser_trust.revoke(tuple(record["binding"]), body.device_id)
        return {"revoked": True}
    except BrowserTrustError as exc:
        raise _trust_error(exc) from exc
    except BrowserLockedError as exc:
        raise HTTPException(status_code=423, detail=str(exc)) from exc
    except BrowserPairingError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


class BrowserConnectIn(BaseModel):
    public_key: str = Field(min_length=1, max_length=512)
    device_name: str = Field(default="Browser", max_length=64)


class BrowserConnectStatusIn(BaseModel):
    request_id: str = Field(min_length=1, max_length=64)
    poll_secret: str = Field(min_length=1, max_length=128)


class BrowserConnectDecisionIn(BaseModel):
    request_id: str = Field(min_length=1, max_length=64)
    code: str = Field(default="", max_length=6)


def _connect_error(exc: BrowserConnectError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail={"code": exc.code, "message": str(exc)})


@router.post("/connect/request")
def request_connection(
    body: BrowserConnectIn,
    request: Request,
    connect_nonce: str | None = Header(default=None, alias="X-Vault-Connect-Nonce"),
) -> dict:
    """Ask the desktop owner to approve this browser; see docs/browser-connection-approval.md."""
    origin = _origin(request)
    expected = request.app.state.connect_nonce
    # The nonce is checked before anything else, so only an allowlisted extension
    # that reached the native host can even learn whether the vault is unlocked.
    if (origin not in browser_discovery.EXTENSION_ORIGINS or not expected or not connect_nonce
            or not hmac.compare_digest(connect_nonce.encode(), expected.encode())):
        raise HTTPException(status_code=403, detail={"code": "origin", "message": "This extension cannot request a connection"})
    try:
        return browser_connects.request(origin, body.public_key, body.device_name)
    except BrowserConnectError as exc:
        raise _connect_error(exc) from exc
    except BrowserTrustError as exc:
        raise _trust_error(exc) from exc


@router.post("/connect/status")
def connection_status(body: BrowserConnectStatusIn, request: Request) -> dict:
    try:
        return browser_connects.status(_origin(request), body.request_id, body.poll_secret)
    except BrowserConnectError as exc:
        raise _connect_error(exc) from exc
    except BrowserTrustError as exc:
        raise _trust_error(exc) from exc


@router.get("/connect/pending")
def pending_connections(token: str = Depends(get_token)) -> dict:
    try:
        return {"items": browser_connects.pending_for(token)}
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail="Desktop vault is locked") from exc


@router.post("/connect/approve")
def approve_connection(body: BrowserConnectDecisionIn, token: str = Depends(get_token)) -> dict:
    try:
        return browser_connects.approve(token, body.request_id, body.code)
    except BrowserConnectError as exc:
        raise _connect_error(exc) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail="Desktop vault is locked") from exc


@router.post("/connect/deny")
def deny_connection(body: BrowserConnectDecisionIn, token: str = Depends(get_token)) -> dict:
    try:
        browser_connects.deny(token, body.request_id)
    except BrowserConnectError as exc:
        raise _connect_error(exc) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail="Desktop vault is locked") from exc
    return {"denied": True}


@router.post("/connect/deny-all")
def deny_all_connections(token: str = Depends(get_token)) -> dict:
    try:
        return {"denied": browser_connects.deny_all(token)}
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail="Desktop vault is locked") from exc


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


class BrowserGenerateIn(BaseModel):
    url: str = Field(default="", max_length=2048)
    request_id: UUID | None = None


@router.post("/generate")
def browser_generate(response: Response, body: BrowserGenerateIn | None = None, vault=Depends(_vault_for_browser)) -> dict:
    response.headers["Cache-Control"] = "no-store"
    try:
        return generate_saved(vault.local, length=24, url=body.url if body else "", request_id=str(body.request_id) if body and body.request_id else None)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Generated password was not saved; try again") from exc


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
    response: Response,
    vault=Depends(_vault_for_browser),
) -> dict:
    response.headers["Cache-Control"] = "no-store"
    try:
        allowed = {item["id"] for item in matches_for_url(vault, body.url)}
        if body.entry_id not in allowed:
            raise BrowserPairingError("The requested entry does not match this page")
        entry = vault.resolve(body.entry_id)
    except (KeyError, ValueError, BrowserPairingError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if body.field == "username":
        return {"username": entry.username}
    if body.field == "password":
        return {"password": entry.password}
    return {"username": entry.username, "password": entry.password}


@router.post("/totp")
def browser_totp(body: BrowserFillIn, response: Response, vault=Depends(_vault_for_browser)) -> dict:
    response.headers["Cache-Control"] = "no-store"
    try:
        allowed = {item["id"] for item in matches_for_url(vault, body.url)}
        if body.entry_id not in allowed:
            raise ValueError()
        result = current_totp(data_for(vault.resolve(body.entry_id))["totp_secret"])
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="No matching account with a valid authenticator key") from exc
    return {key: result[key] for key in ("code", "expires_at", "remaining_seconds")}

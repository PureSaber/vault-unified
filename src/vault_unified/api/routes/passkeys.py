from contextlib import contextmanager
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from vault_unified.api.deps import get_token
from vault_unified.browser_pairing import BrowserPairingError, browser_pairings
from vault_unified.local_store import EntryTransactionConflict
from vault_unified.passkeys import PasskeyError
from vault_unified.passkey_requests import requests

router = APIRouter(tags=["passkeys"])


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Begin(Input):
    operation: Literal["create", "get"]
    origin: str = Field(min_length=1, max_length=2048)
    options: dict
    request_id: str = Field(default="", max_length=36)


class Identifier(Input):
    request_id: str = Field(min_length=20, max_length=100)


class Approval(Identifier):
    confirm: StrictBool = False
    password: str = Field(min_length=1, max_length=4096)
    entry_id: str = Field(default="", max_length=100)
    credential_id: str = Field(default="", max_length=1500)


class Rejection(Identifier):
    fallback: StrictBool = False


@contextmanager
def guard(response):
    response.headers["Cache-Control"] = "no-store"
    try: yield
    except (BrowserPairingError, PermissionError):
        raise HTTPException(401, "Unlock and reconnect the browser") from None
    except EntryTransactionConflict:
        raise HTTPException(409, "Vault changed; retry the Passkey request") from None
    except PasskeyError as exc:
        raise HTTPException(400, str(exc)) from None
    except (ValueError, TypeError, KeyError, OSError):
        raise HTTPException(400, "Passkey request could not be completed") from None


def browser_token(value: str | None = Header(default=None, alias="X-Vault-Browser-Token")):
    if not value: raise HTTPException(401, "Missing browser pairing")
    return value


@router.post("/browser/passkeys/begin")
def begin(body: Begin, request: Request, response: Response, token=Depends(browser_token)):
    with guard(response): return requests.begin(token, request.headers.get("origin", ""), body.origin, body.operation, body.options, body.request_id)


@router.post("/browser/passkeys/status")
def status(body: Identifier, request: Request, response: Response, token=Depends(browser_token)):
    with guard(response): return requests.status(token, request.headers.get("origin", ""), body.request_id)


@router.post("/browser/passkeys/cancel")
def cancel(body: Identifier, request: Request, response: Response, token=Depends(browser_token)):
    with guard(response):
        browser_pairings.vault_for(token, request.headers.get("origin", ""), touch=False)
        requests.cancel_browser(token, request.headers.get("origin", ""), body.request_id)
        return {"cancelled": True}


@router.get("/passkeys/pending")
def pending(response: Response, token=Depends(get_token)):
    with guard(response): return requests.list(token)


@router.post("/passkeys/approve")
def approve(body: Approval, response: Response, token=Depends(get_token)):
    with guard(response):
        if body.confirm is not True: raise PasskeyError("Confirm the website and Passkey request")
        return requests.approve(token, body.request_id, body.password, entry_id=body.entry_id, credential_id=body.credential_id)


@router.post("/passkeys/reject")
def reject(body: Rejection, response: Response, token=Depends(get_token)):
    with guard(response):
        requests.reject(token, body.request_id, fallback=body.fallback)
        return {"cancelled": True}

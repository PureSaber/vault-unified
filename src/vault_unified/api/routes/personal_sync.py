from typing import Literal
from contextlib import contextmanager

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from vault_unified.api.deps import get_token
from vault_unified.local_store import EntryTransactionConflict
from vault_unified.personal_sync.connections import connections
from vault_unified.personal_sync.codec import STATE_NAMESPACE, ProtocolError
from vault_unified.personal_sync.transport import StorageUnavailable
from vault_unified.session import sessions

router = APIRouter(prefix="/personal-sync", tags=["personal-sync"])


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Setup(Input):
    provider: Literal["folder", "webdav"]
    mode: Literal["create", "join"]
    location: str = Field(min_length=1, max_length=2000)
    label: str = Field(min_length=1, max_length=100)
    automatic: StrictBool = False
    code: str = Field(default="", max_length=100)
    username: str = Field(default="", max_length=200)
    password: str = Field(default="", max_length=512)


class Approval(Input):
    confirm: StrictBool = False


class PreviewToken(Approval):
    preview_token: str = Field(min_length=20, max_length=100)


class Run(Input):
    automatic: StrictBool = False


class Settings(Input):
    automatic: StrictBool
    label: str = Field(min_length=1, max_length=100)


class Resolve(Approval):
    generation: int = Field(ge=0, strict=True)
    choices: dict[str, Literal["local", "remote"]] = Field(min_length=1, max_length=1000)


@contextmanager
def context(token, response):
    response.headers["Cache-Control"] = "no-store"
    try:
        vault = sessions.get(token, touch=False)
        def check():
            if sessions.get(token, touch=False) is not vault:
                raise PermissionError()
        yield vault.local, check
        check()
    except PermissionError:
        raise HTTPException(401, "Unlock the vault again") from None
    except EntryTransactionConflict as error:
        raise HTTPException(409, str(error)) from None
    except StorageUnavailable as error:
        raise HTTPException(503, str(error)) from None
    except ProtocolError as error:
        raise HTTPException(400, str(error)) from None
    except (ValueError, OSError, KeyError, TypeError):
        raise HTTPException(400, "Synchronization could not preserve the data; reconnect or retry") from None


def require_approval(body):
    if not body.confirm: raise HTTPException(400, "Review and confirm this operation first")


@router.get("/status")
def status(response: Response, token: str = Depends(get_token)):
    with context(token, response) as (local, _): return connections.status(local)


@router.post("/preview")
def preview(body: Setup, response: Response, token: str = Depends(get_token)):
    with context(token, response) as (local, check): return connections.preview(local, token, body.model_dump(), check)


@router.post("/cancel")
def cancel(body: PreviewToken, response: Response, token: str = Depends(get_token)):
    with context(token, response):
        connections.cancel(token, body.preview_token)
        return {"cancelled": True}


@router.post("/connect")
def connect(body: PreviewToken, response: Response, token: str = Depends(get_token)):
    require_approval(body)
    with context(token, response) as (local, check): return connections.apply(local, token, body.preview_token, check)


@router.post("/run")
def synchronize(body: Run, response: Response, token: str = Depends(get_token)):
    with context(token, response) as (local, check):
        initial = local.metadata_value(STATE_NAMESPACE)
        def connected():
            check()
            current = local.metadata_value(STATE_NAMESPACE)
            if initial is None or current is None or current["device"] != initial["device"] or current["connection"].get("disabled"):
                raise ProtocolError("Synchronization connection changed")
            if body.automatic and not current["connection"]["automatic"]:
                raise ProtocolError("Automatic synchronization was stopped")
        return connections.synchronize(local, connected, automatic=body.automatic)


@router.put("/settings")
def settings(body: Settings, response: Response, token: str = Depends(get_token)):
    with context(token, response) as (local, _):
        connections.settings(local, automatic=body.automatic, label=body.label)
        return connections.status(local)


@router.post("/code")
def code(body: Approval, response: Response, token: str = Depends(get_token)):
    require_approval(body)
    with context(token, response) as (local, _): return {"code": connections.code(local)}


@router.post("/disconnect")
def disconnect(body: Approval, response: Response, token: str = Depends(get_token)):
    require_approval(body)
    with context(token, response) as (local, _): return connections.disconnect(local)


@router.post("/code/copy")
def copy_code(body: Approval, response: Response, token: str = Depends(get_token)):
    from vault_unified.clipboard import copy_to_clipboard
    require_approval(body)
    with context(token, response) as (local, check):
        code = connections.code(local)
        check()
        copy_to_clipboard(code)
        return {"copied": True, "clear_after": 45}


@router.get("/conflicts")
def conflicts(response: Response, reveal: bool = False, token: str = Depends(get_token)):
    with context(token, response) as (local, _): return connections.conflicts(local, reveal=reveal)


@router.post("/resolve")
def resolve(body: Resolve, response: Response, token: str = Depends(get_token)):
    require_approval(body)
    with context(token, response) as (local, _):
        connections.resolve(local, body.choices, body.generation)
        return {"resolved": True}

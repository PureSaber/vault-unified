from contextlib import contextmanager
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from vault_unified.api.deps import get_token
from vault_unified.clipboard import copy_to_clipboard
from vault_unified.local_store import EntryTransactionConflict
from vault_unified.restore_preview import RestorePreviewError
from vault_unified.sharing.client import RemoteError
from vault_unified.sharing.desktop import sharing
from vault_unified.sharing.desktop import invitation, state_for
from vault_unified.sharing.protocol import public_identity
from vault_unified.sharing.protocol import SharingError

router = APIRouter(prefix="/sharing", tags=["sharing"])


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Confirm(Input):
    confirm: StrictBool = False


class Connection(Confirm):
    server: str = Field(min_length=1, max_length=2000)
    admin_token: str = Field(default="", max_length=256, repr=False)


class Options(Input):
    action: Literal["share", "revoke-share", "create-family", "join-family", "invite", "approve-member", "remove-member", "revoke-invite", "save-entry", "trash-entry", "restore-entry", "restore-history"]
    family_id: str = Field(default="", max_length=32)
    entry_id: str = Field(default="", max_length=100)
    fields: list[Literal["username", "password", "url", "notes"]] = Field(default_factory=list, max_length=4)
    hours: int = Field(default=24, ge=1, le=720, strict=True)
    max_reads: int = Field(default=1, ge=1, le=100, strict=True)
    name: str = Field(default="", max_length=100)
    invite: str = Field(default="", max_length=6000, repr=False)
    role: Literal["reader", "editor"] = "reader"
    member_id: str = Field(default="", max_length=64)
    pending_id: str = Field(default="", max_length=32)
    values: dict[str, str] = Field(default_factory=dict, max_length=5, repr=False)
    history_index: int = Field(default=0, ge=0, le=19, strict=True)
    replace_pending_id: str = Field(default="", max_length=32)


class Preview(Input):
    options: Options


class Apply(Confirm):
    options: Options
    preview_token: str = Field(min_length=32, max_length=100)


class Cancel(Input):
    preview_token: str = Field(min_length=32, max_length=100)


class InvitationCopy(Confirm):
    code: str = Field(min_length=1, max_length=6000, repr=False)


@contextmanager
def guard(response):
    response.headers["Cache-Control"] = "no-store"
    try: yield
    except PermissionError: raise HTTPException(401, "Unlock the vault again") from None
    except RemoteError as error: raise HTTPException(409 if error.status == 409 else 400, str(error)) from None
    except (EntryTransactionConflict, RestorePreviewError) as error: raise HTTPException(409, str(error)) from None
    except SharingError as error: raise HTTPException(400, str(error)) from None
    except (ValueError, TypeError, KeyError, OSError): raise HTTPException(400, "Sharing could not complete; review the pending operation") from None


def consent(body):
    if body.confirm is not True: raise HTTPException(400, "Review and confirm this sharing operation")


@router.get("/status")
def status(response: Response, token=Depends(get_token)):
    with guard(response): return sharing.status(token)


@router.put("/connection")
def connection(body: Connection, response: Response, token=Depends(get_token)):
    consent(body)
    with guard(response): return sharing.configure(token, body.server, body.admin_token)


@router.post("/preview")
def preview(body: Preview, response: Response, token=Depends(get_token)):
    with guard(response): return sharing.preview(token, body.options.model_dump())


@router.post("/cancel")
def cancel(body: Cancel, response: Response, token=Depends(get_token)):
    with guard(response):
        sharing.cancel(token, body.preview_token)
        return {"cancelled": True}


@router.post("/apply")
def apply(body: Apply, response: Response, token=Depends(get_token)):
    consent(body)
    with guard(response): return sharing.apply(token, body.preview_token, body.options.model_dump())


@router.post("/pending/{oid}/{action}")
def pending_action(oid: str, action: Literal["retry", "discard", "review"], body: Confirm, response: Response, token=Depends(get_token)):
    consent(body)
    with guard(response):
        if action == "review": return sharing.review_pending(token, oid)
        return sharing.retry(token, oid) if action == "retry" else sharing.discard(token, oid)


@router.post("/shares/{sid}/link")
def link(sid: str, body: Confirm, response: Response, token=Depends(get_token)):
    consent(body)
    with guard(response): return {"link": sharing.link(token, sid)}


@router.post("/shares/{sid}/copy")
def copy_link(sid: str, body: Confirm, response: Response, token=Depends(get_token)):
    consent(body)
    with guard(response):
        copy_to_clipboard(sharing.link(token, sid))
        return {"copied": True}


@router.get("/families/{gid}")
def family(gid: str, response: Response, token=Depends(get_token)):
    with guard(response): return sharing.view(token, gid)


@router.post("/invitations/copy")
def copy_invitation(body: InvitationCopy, response: Response, token=Depends(get_token)):
    consent(body)
    with guard(response), sharing.context(token) as (vault, _):
        value = invitation(body.code); state = state_for(vault.local)
        if value["owner"] != public_identity(state["identity"])["signing_key"]: raise SharingError("Only the inviter can copy this invitation")
        copy_to_clipboard(body.code)
        return {"copied": True}


@router.post("/families/{gid}/refresh")
def refresh(gid: str, response: Response, token=Depends(get_token)):
    with guard(response): return sharing.refresh(token, gid)


@router.post("/families/{gid}/entry/{eid}")
def entry(gid: str, eid: str, body: Confirm, response: Response, token=Depends(get_token)):
    consent(body)
    with guard(response): return sharing.view(token, gid, entry_id=eid, reveal=True)


@router.post("/families/{gid}/entry/{eid}/copy/{field}")
def copy_entry(gid: str, eid: str, field: Literal["username", "password"], body: Confirm, response: Response, token=Depends(get_token)):
    consent(body)
    with guard(response):
        value = sharing.view(token, gid, entry_id=eid, reveal=True)
        if value["trashed_at"]: raise SharingError("Restore this shared account before copying it")
        copy_to_clipboard(value[field])
        return {"copied": True}


@router.get("/families/{gid}/pending")
def pending(gid: str, response: Response, token=Depends(get_token)):
    with guard(response): return sharing.pending_members(token, gid)

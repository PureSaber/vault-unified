from __future__ import annotations

from fastapi import Header, HTTPException, Request

from vault_unified.manager import UnifiedVault
from vault_unified.session import sessions

LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}


def require_loopback(request: Request) -> None:
    host = (request.client.host if request.client else "") or ""
    if host not in LOOPBACK_HOSTS:
        raise HTTPException(status_code=403, detail="Loopback only")


def get_token(authorization: str | None = Header(default=None)) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing authorization")
    return authorization.removeprefix("Bearer ").strip()


def get_vault(authorization: str | None = Header(default=None)) -> UnifiedVault:
    token = get_token(authorization)
    try:
        return sessions.get(token)
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

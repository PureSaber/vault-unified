from __future__ import annotations

from fastapi import Header, HTTPException

from vault_unified.manager import UnifiedVault
from vault_unified.session import sessions


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

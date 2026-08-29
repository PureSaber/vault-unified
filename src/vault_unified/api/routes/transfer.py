from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from vault_unified.api.deps import get_vault
from vault_unified.api.schemas import TransferExportIn, TransferImportIn
from vault_unified.manager import UnifiedVault
from vault_unified.personal_data import PersonalDataError
from vault_unified.transfer import export_transfer, import_entries, parse_transfer


router = APIRouter(prefix="/transfer", tags=["transfer"])


def _confirm(confirm_plaintext: bool) -> None:
    if not confirm_plaintext:
        raise HTTPException(
            status_code=400,
            detail="confirm_plaintext=true is required because transfers contain plaintext secrets",
        )


@router.post("/export")
def export_vault(
    body: TransferExportIn,
    vault: UnifiedVault = Depends(get_vault),
) -> dict:
    _confirm(body.confirm_plaintext)
    try:
        content, filename, mime_type = export_transfer(vault, body.format)
    except (OSError, ValueError, PersonalDataError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "format": body.format,
        "filename": filename,
        "mime_type": mime_type,
        "content": content,
        "warning": "This export contains plaintext secrets. Store it only briefly and delete it after import.",
    }


@router.post("/import")
def import_vault(
    body: TransferImportIn,
    vault: UnifiedVault = Depends(get_vault),
) -> dict:
    _confirm(body.confirm_plaintext)
    try:
        entries = parse_transfer(body.content, body.format)
        result = import_entries(vault, entries)
    except (OSError, ValueError, PersonalDataError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        **result,
        "warning": "Imported entries are local changes. Review them, then run the normal sync preview before pushing to any external source.",
    }

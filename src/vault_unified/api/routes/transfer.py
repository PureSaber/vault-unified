from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from vault_unified.api.deps import get_token, get_vault
from vault_unified.api.schemas import (
    TransferExportIn,
    TransferImportApplyIn,
    TransferImportCancelIn,
    TransferImportIn,
    TransferImportUndoIn,
)
from vault_unified.backup_manager import create_manual_backup
from vault_unified.crypto import decrypt_payload
from vault_unified.import_flow import (
    ImportFlowError,
    ImportPreviewExpired,
    ImportSessionMismatch,
    build_preview,
    import_flow_store,
    new_receipt,
    prepare_apply,
)
from vault_unified.local_store import EntryTransactionConflict
from vault_unified.manager import UnifiedVault
from vault_unified.personal_data import PersonalDataError
from vault_unified.transfer import export_transfer


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


@router.post("/import/preview")
def preview_import(
    body: TransferImportIn,
    token: str = Depends(get_token),
    vault: UnifiedVault = Depends(get_vault),
) -> dict:
    _confirm(body.confirm_plaintext)
    before_digest = vault.local.state_digest()
    before_generation = vault.local.generation
    try:
        source_digest, items, public = build_preview(vault, body.content, body.format)
    except (ValueError, PersonalDataError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if (
        vault.local.state_digest() != before_digest
        or vault.local.generation != before_generation
    ):
        raise HTTPException(
            status_code=500,
            detail="Import preview modified the vault; the preview was discarded",
        )
    intent = import_flow_store.issue(
        session_token=token,
        format_name=body.format,
        source_file_digest=source_digest,
        before_vault_digest=before_digest,
        before_generation=before_generation,
        items=items,
    )
    return {
        **public,
        "preview_token": intent.token,
        "source_file_digest": source_digest,
        "expires_at": datetime.fromtimestamp(
            intent.expires_at,
            tz=timezone.utc,
        ).isoformat(),
        "warning": "Preview only: no vault data was changed and no external service was contacted.",
    }


@router.post("/import/apply")
def apply_import(
    body: TransferImportApplyIn,
    token: str = Depends(get_token),
    vault: UnifiedVault = Depends(get_vault),
) -> dict:
    try:
        intent = import_flow_store.consume(body.preview_token, session_token=token)
    except (ImportPreviewExpired, ImportSessionMismatch) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if (
        vault.local.state_digest() != intent.before_vault_digest
        or vault.local.generation != intent.before_generation
    ):
        raise HTTPException(
            status_code=409,
            detail="Vault changed after the import preview; create a new preview",
        )
    try:
        candidates, added_ids, updated_ids, skipped = prepare_apply(
            vault,
            intent,
            (decision.model_dump() for decision in body.decisions),
        )
    except ImportFlowError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not candidates:
        return {
            "applied": False,
            "added": 0,
            "updated": 0,
            "skipped": skipped,
            "receipt": None,
            "warning": "Nothing was imported; the vault was not written.",
        }

    backup = None
    try:
        backup = create_manual_backup(
            vault.vault_path,
            vault.local.credential,
        )
        vault.local.commit_import_batch(
            candidates,
            updated_entry_ids=set(updated_ids),
            expected_generation=intent.before_generation,
            expected_digest=intent.before_vault_digest,
        )
    except EntryTransactionConflict as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                "Import was not applied because the vault changed. "
                "No vault entries were changed; a verified pre-import backup may remain."
            ),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                "Import was not applied. No vault entries were changed; "
                "a verified pre-import backup may remain."
            ),
        ) from exc

    after_digest = vault.local.state_digest()
    after_generation = vault.local.generation
    receipt = new_receipt(
        session_token=token,
        intent=intent,
        after_vault_digest=after_digest,
        after_generation=after_generation,
        added_ids=added_ids,
        updated_ids=updated_ids,
        backup_path=str(backup.path),
    )
    import_flow_store.add_receipt(receipt)
    return {
        "applied": True,
        "added": len(added_ids),
        "updated": len(updated_ids),
        "skipped": skipped,
        "receipt": receipt.public(),
        "warning": (
            "Imported entries remain local changes. Review them and use a separate "
            "sync preview before sending anything to an external service."
        ),
    }


@router.post("/import/cancel")
def cancel_import(
    body: TransferImportCancelIn,
    token: str = Depends(get_token),
    vault: UnifiedVault = Depends(get_vault),
) -> dict:
    _ = vault
    try:
        import_flow_store.cancel(body.preview_token, session_token=token)
    except (ImportPreviewExpired, ImportSessionMismatch) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"cancelled": True, "message": "Import preview discarded; no data was written"}


@router.post("/import/undo")
def undo_import(
    body: TransferImportUndoIn,
    token: str = Depends(get_token),
    vault: UnifiedVault = Depends(get_vault),
) -> dict:
    try:
        receipt = import_flow_store.receipt(body.transaction_id, session_token=token)
        if receipt.undone:
            raise ImportFlowError("This import was already undone")
        if (
            vault.local.state_digest() != receipt.after_vault_digest
            or vault.local.generation != receipt.after_generation
        ):
            raise EntryTransactionConflict(
                "Vault changed after the import; undo was refused"
            )
        backup_path = Path(receipt.backup_path)
        payload = decrypt_payload(vault.local.credential, backup_path.read_bytes())
        vault.local.restore_import_payload(
            payload,
            expected_generation=receipt.after_generation,
            expected_digest=receipt.after_vault_digest,
            restored_digest=receipt.before_vault_digest,
        )
        updated = import_flow_store.mark_undone(
            body.transaction_id,
            session_token=token,
        )
    except (EntryTransactionConflict, ImportFlowError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(
            status_code=500,
            detail="Import undo failed; the current vault was not changed",
        ) from exc
    return {
        "undone": True,
        "receipt": updated.public(),
        "restored_vault_digest": vault.local.state_digest(),
        "message": "The vault was restored to its exact pre-import entry state",
    }


@router.post("/import")
def direct_import_is_disabled(
    body: TransferImportIn,
    vault: UnifiedVault = Depends(get_vault),
) -> dict:
    _ = body, vault
    raise HTTPException(
        status_code=409,
        detail="Direct import is disabled; create an import preview and confirm it",
    )

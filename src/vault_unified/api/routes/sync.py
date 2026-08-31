from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from vault_unified.api.deps import get_token, get_vault
from vault_unified.api.schemas import (
    ConflictResolveIn,
    SyncExecuteIn,
    SyncPreferencesIn,
    SyncPreferencesOut,
    SyncPreviewIn,
)
from vault_unified.manager import UnifiedVault
from vault_unified.models import (
    PrimarySource,
    SecretEntry,
    Source,
    SyncPreferences,
)
from vault_unified.sync.preview import (
    SyncPreviewExpired,
    SyncPreviewSessionMismatch,
    canonical_digest,
    preview_store,
    sync_state_fingerprint,
)

router = APIRouter(tags=["sync"])


@router.get("/status")
def status(vault: UnifiedVault = Depends(get_vault)) -> dict:
    return {"components": vault.status()}


@router.get("/sync/preferences", response_model=SyncPreferencesOut)
def get_preferences(vault: UnifiedVault = Depends(get_vault)) -> SyncPreferencesOut:
    prefs = vault.get_prefs()
    return SyncPreferencesOut(**prefs.to_dict())


@router.put("/sync/preferences", response_model=SyncPreferencesOut)
def update_preferences(
    body: SyncPreferencesIn,
    vault: UnifiedVault = Depends(get_vault),
) -> SyncPreferencesOut:
    prefs = vault.get_prefs()
    data = prefs.to_dict()
    updates = body.model_dump(exclude_none=True)
    if "enabled_sources" in body.model_fields_set:
        # Explicit null retains the legacy "all sources" compatibility mode.
        updates["enabled_sources"] = body.enabled_sources
    for key, value in updates.items():
        data[key] = value
    if "primary" in data:
        try:
            data["primary"] = PrimarySource(data["primary"]).value
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid primary source") from exc
    try:
        updated = SyncPreferences.from_dict(data)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    vault.save_prefs(updated)
    return SyncPreferencesOut(**vault.get_prefs().to_dict())


def _resolve_sources(
    vault: UnifiedVault,
    requested: list[str] | None,
    *,
    allow_disabled_explicit: bool = False,
) -> list[Source]:
    enabled = vault.get_prefs().get_enabled_sources()
    enabled_set = set(enabled)
    if requested is None:
        selected = list(enabled)
    else:
        selected = []
        for value in requested:
            try:
                source = Source(value)
            except ValueError as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid sync source: {value}",
                ) from exc
            if source == Source.LOCAL:
                raise HTTPException(
                    status_code=400,
                    detail="Local is not an external sync source",
                )
            if source not in enabled_set and not allow_disabled_explicit:
                raise HTTPException(
                    status_code=400,
                    detail=f"Source {value} is disabled in sync preferences",
                )
            if source not in selected:
                selected.append(source)
    if not selected:
        raise HTTPException(
            status_code=400,
            detail="No external sources are enabled for this preview",
        )
    return selected


@router.post("/sync/preview")
def preview_sync(
    body: SyncPreviewIn,
    session_token: str = Depends(get_token),
    vault: UnifiedVault = Depends(get_vault),
) -> dict:
    if not body.include_pull and not body.include_push:
        raise HTTPException(
            status_code=400,
            detail="Preview must include pull, push, or both",
        )
    sources = _resolve_sources(
        vault,
        body.sources,
        allow_disabled_explicit=body.sources is not None,
    )
    before = sync_state_fingerprint(vault)
    try:
        plan = vault.preview_sync(
            sources,
            include_pull=body.include_pull,
            include_push=body.include_push,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    after = sync_state_fingerprint(vault)
    if before != after:
        raise HTTPException(
            status_code=500,
            detail="Sync preview modified local state; execution was blocked",
        )

    state_digest = plan.pop("_state_digest")
    operation_digest = canonical_digest(plan["operations"])
    intent = preview_store.issue(
        session_token=session_token,
        sources=tuple(source.value for source in sources),
        include_pull=body.include_pull,
        include_push=body.include_push,
        local_fingerprint=before,
        plan_digest=state_digest,
        operation_digest=operation_digest,
    )
    return {
        **plan,
        "preview_token": intent.token,
        "expires_at": datetime.fromtimestamp(
            intent.expires_at, tz=timezone.utc
        ).isoformat(),
    }


@router.post("/sync/execute")
def execute_previewed_sync(
    body: SyncExecuteIn,
    session_token: str = Depends(get_token),
    vault: UnifiedVault = Depends(get_vault),
) -> dict:
    try:
        intent = preview_store.consume(
            body.preview_token,
            session_token=session_token,
        )
    except (SyncPreviewExpired, SyncPreviewSessionMismatch) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if sync_state_fingerprint(vault) != intent.local_fingerprint:
        raise HTTPException(
            status_code=409,
            detail="Local vault or sync settings changed; create a new preview",
        )

    sources = [Source(value) for value in intent.sources]
    enabled_sources = set(vault.get_prefs().get_enabled_sources())
    if any(source not in enabled_sources for source in sources):
        raise HTTPException(
            status_code=409,
            detail="Enable every selected connection before executing this preview",
        )
    try:
        fresh_plan = vault.preview_sync(
            sources,
            include_pull=intent.include_pull,
            include_push=intent.include_push,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                "The selected remote sources changed or became unavailable; "
                "create a new preview"
            ),
        ) from exc
    fresh_digest = fresh_plan.pop("_state_digest")
    if fresh_digest != intent.plan_digest:
        raise HTTPException(
            status_code=409,
            detail="Remote sync state changed; create a new preview",
        )

    approved_operations = fresh_plan["operations"]
    if canonical_digest(approved_operations) != intent.operation_digest:
        raise HTTPException(
            status_code=409,
            detail="Sync operation set changed; create a new preview",
        )

    result = vault.execute_sync(
        sources,
        include_pull=intent.include_pull,
        include_push=intent.include_push,
        approved_operations=approved_operations,
    )
    return result.to_dict()


def _preview_required() -> None:
    raise HTTPException(
        status_code=409,
        detail="A fresh /sync/preview token is required; use /sync/execute",
    )


@router.post("/sync")
def sync_bidirectional(vault: UnifiedVault = Depends(get_vault)) -> dict:
    _ = vault
    _preview_required()


@router.post("/sync/pull/{source}")
def pull_source(
    source: str,
    vault: UnifiedVault = Depends(get_vault),
) -> dict:
    _ = source, vault
    _preview_required()


@router.post("/sync/push")
def push_dirty(vault: UnifiedVault = Depends(get_vault)) -> dict:
    _ = vault
    _preview_required()


@router.post("/sync/push/{entry_id}")
def push_entry(
    entry_id: str,
    vault: UnifiedVault = Depends(get_vault),
) -> dict:
    _ = entry_id, vault
    _preview_required()


@router.get("/sync/conflicts")
def list_conflicts(
    reveal: bool = False,
    vault: UnifiedVault = Depends(get_vault),
) -> list:
    return [c.to_dict(reveal=reveal) for c in vault.list_conflicts()]


@router.post("/sync/conflicts/{conflict_id}/resolve")
def resolve_conflict(
    conflict_id: str,
    body: ConflictResolveIn,
    vault: UnifiedVault = Depends(get_vault),
) -> dict:
    merged = None
    if body.choice == "merge" and not body.merged:
        raise HTTPException(status_code=400, detail="merged payload required")
    if body.merged:
        merged = SecretEntry.from_dict(body.merged)
    try:
        entry = vault.resolve_conflict(conflict_id, body.choice, merged)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"resolved": entry.title, "id": entry.id}

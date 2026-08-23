from __future__ import annotations

import shutil

from fastapi import APIRouter, Depends, HTTPException

from vault_unified.adapters.registry import clear_adapter_cache, get_adapter
from vault_unified.api.deps import get_vault
from vault_unified.api.schemas import (
    IntegrationOut,
    IntegrationTestOut,
    IntegrationUpdateIn,
)
from vault_unified.integration_credentials import (
    CredentialStoreError,
    clear_source_settings,
    integration_snapshot,
    list_integration_snapshots,
    update_source_settings,
)
from vault_unified.manager import UnifiedVault
from vault_unified.models import Source

router = APIRouter(prefix="/integrations", tags=["integrations"])


def _source(value: str) -> Source:
    try:
        source = Source(value)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Unknown integration source") from exc
    if source == Source.LOCAL:
        raise HTTPException(status_code=404, detail="Unknown integration source")
    return source


def _out(snapshot: dict) -> IntegrationOut:
    source = _source(snapshot["source"])
    adapter = get_adapter(source)
    return IntegrationOut(
        **snapshot,
        cli_installed=shutil.which(getattr(adapter, "cli_name", "")) is not None,
    )


@router.get("", response_model=list[IntegrationOut])
def list_integrations(
    vault: UnifiedVault = Depends(get_vault),
) -> list[IntegrationOut]:
    _ = vault
    return [_out(snapshot) for snapshot in list_integration_snapshots()]


@router.put("/{source_name}", response_model=IntegrationOut)
def update_integration(
    source_name: str,
    body: IntegrationUpdateIn,
    vault: UnifiedVault = Depends(get_vault),
) -> IntegrationOut:
    _ = vault
    source = _source(source_name)
    try:
        update_source_settings(source.value, body.values, body.clear)
    except CredentialStoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    clear_adapter_cache()
    return _out(integration_snapshot(source.value))


@router.delete("/{source_name}", response_model=IntegrationOut)
def delete_integration(
    source_name: str,
    vault: UnifiedVault = Depends(get_vault),
) -> IntegrationOut:
    _ = vault
    source = _source(source_name)
    try:
        clear_source_settings(source.value)
    except CredentialStoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    clear_adapter_cache()
    return _out(integration_snapshot(source.value))


@router.post("/{source_name}/test", response_model=IntegrationTestOut)
def test_integration(
    source_name: str,
    vault: UnifiedVault = Depends(get_vault),
) -> IntegrationTestOut:
    _ = vault
    source = _source(source_name)
    clear_adapter_cache()
    adapter = get_adapter(source)
    try:
        configured = adapter.is_configured()
        available = configured and adapter.is_available()
        message = "Connection succeeded" if available else adapter.status_message()
    except Exception as exc:
        configured = False
        available = False
        message = f"Connection test failed ({type(exc).__name__})"
    return IntegrationTestOut(
        source=source.value,
        configured=configured,
        available=available,
        message=message,
    )

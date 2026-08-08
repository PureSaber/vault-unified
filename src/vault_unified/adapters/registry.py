from __future__ import annotations

from vault_unified.adapters.base import VaultAdapter
from vault_unified.adapters.bitwarden import BitwardenAdapter
from vault_unified.adapters.gopass import GopassAdapter
from vault_unified.adapters.keepassxc import KeePassXCAdapter
from vault_unified.adapters.proton_pass import ProtonPassAdapter
from vault_unified.models import Source

_ADAPTERS: dict[Source, type[VaultAdapter]] = {
    Source.PROTON_PASS: ProtonPassAdapter,
    Source.BITWARDEN: BitwardenAdapter,
    Source.KEEPASSXC: KeePassXCAdapter,
    Source.GOPASS: GopassAdapter,
}

REMOTE_SOURCES: list[Source] = list(_ADAPTERS.keys())

_instances: dict[Source, VaultAdapter] = {}


def get_adapter(source: Source) -> VaultAdapter:
    cls = _ADAPTERS.get(source)
    if cls is None:
        raise ValueError(f"No adapter for source: {source}")
    if source not in _instances:
        _instances[source] = cls()
    return _instances[source]


def clear_adapter_cache() -> None:
    _instances.clear()


def all_remote_adapters() -> list[VaultAdapter]:
    return [get_adapter(source) for source in REMOTE_SOURCES]


def configured_remote_sources() -> list[Source]:
    return [source for source in REMOTE_SOURCES if get_adapter(source).is_configured()]

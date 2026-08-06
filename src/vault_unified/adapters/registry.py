from __future__ import annotations

from vault_unified.adapters.bitwarden import BitwardenAdapter
from vault_unified.adapters.proton_pass import ProtonPassAdapter
from vault_unified.models import Source

_ADAPTERS = {
    Source.PROTON_PASS: ProtonPassAdapter,
    Source.BITWARDEN: BitwardenAdapter,
}


def get_adapter(source: Source) -> BitwardenAdapter | ProtonPassAdapter:
    cls = _ADAPTERS.get(source)
    if cls is None:
        raise ValueError(f"No adapter for source: {source}")
    return cls()


def all_remote_adapters() -> list:
    return [cls() for cls in _ADAPTERS.values()]

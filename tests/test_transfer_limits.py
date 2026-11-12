from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from vault_unified.api.routes.transfer import export_vault
from vault_unified.api.schemas import TransferExportIn
from vault_unified.import_flow import inspect_transfer
from vault_unified.models import SecretEntry
from vault_unified.transfer import MAX_TRANSFER_BYTES, MAX_TRANSFER_ENTRIES, export_transfer, parse_transfer


def _vault(entries):
    return SimpleNamespace(local=SimpleNamespace(list_entries=lambda: entries))


@pytest.mark.parametrize("format_name", ["json", "csv"])
def test_export_rejects_more_than_import_entry_limit(format_name):
    vault = _vault([SecretEntry(title=f"Generated {index}") for index in range(MAX_TRANSFER_ENTRIES + 1)])
    with pytest.raises(HTTPException) as rejected:
        export_vault(TransferExportIn(format=format_name, confirm_plaintext=True), vault=vault)
    assert rejected.value.status_code == 400
    assert "5,000" in rejected.value.detail
    assert "encrypted backup" in rejected.value.detail.lower()


@pytest.mark.parametrize("format_name", ["json", "csv"])
def test_export_at_entry_limit_can_be_imported(format_name):
    vault = _vault([SecretEntry(title=f"Generated {index}") for index in range(MAX_TRANSFER_ENTRIES)])
    content, _, _ = export_transfer(vault, format_name)
    assert len(parse_transfer(content, format_name)) == MAX_TRANSFER_ENTRIES
    _, rows, _ = inspect_transfer(content, format_name)
    assert len(rows) == MAX_TRANSFER_ENTRIES
    assert all(row.error == "" for row in rows)


@pytest.mark.parametrize("format_name", ["json", "csv"])
def test_export_byte_limit_uses_utf8_and_accepts_exact_boundary(format_name):
    # Each field remains below its own import bound; the final field brings the
    # serialized artifact to precisely 10 MiB, including format overhead.
    entries = [SecretEntry(title=f"Generated {index}", notes="x" * 99_000) for index in range(105)]
    entries.append(SecretEntry(title="Boundary", notes=""))
    vault = _vault(entries)
    baseline, _, _ = export_transfer(vault, format_name)
    remaining = MAX_TRANSFER_BYTES - len(baseline.encode("utf-8"))
    assert 0 < remaining < 100_000
    entries[-1].notes = "x" * remaining
    content, _, _ = export_transfer(vault, format_name)
    assert len(content.encode("utf-8")) == MAX_TRANSFER_BYTES
    assert len(parse_transfer(content, format_name)) == len(entries)
    _, rows, _ = inspect_transfer(content, format_name)
    assert len(rows) == len(entries)
    assert all(row.error == "" for row in rows)

    entries[-1].notes += "界"
    with pytest.raises(HTTPException) as rejected:
        export_vault(TransferExportIn(format=format_name, confirm_plaintext=True), vault=vault)
    assert rejected.value.status_code == 400
    assert "10 MiB" in rejected.value.detail
    assert "encrypted backup" in rejected.value.detail.lower()

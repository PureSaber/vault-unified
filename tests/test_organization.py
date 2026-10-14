from __future__ import annotations

from datetime import datetime, timedelta, timezone
import copy

import pytest
from fastapi.testclient import TestClient

from vault_unified.api.app import create_app
from vault_unified.browser_pairing import matches_for_url
from vault_unified.crypto import decrypt_payload
from vault_unified.manager import UnifiedVault
from vault_unified.models import SecretEntry, SyncStatus
from vault_unified.organization import ORGANIZATION_KEY, organization_for, prepare_action, purge_expired
from vault_unified.personal_data import merge_personal_metadata, update_data
from vault_unified.session import sessions
from vault_unified.v3_crypto import create_v3_file


@pytest.fixture
def organized_api(tmp_path, monkeypatch):
    monkeypatch.setenv("VAULT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("VAULT_CONFIG_DIR", str(tmp_path / "config"))
    path = tmp_path / "active.vault"
    monkeypatch.setenv("VAULT_FILE", str(path))
    sessions.lock_all()
    bootstrap = "generated-organization-bootstrap-secret"
    with TestClient(create_app(bootstrap_secret=bootstrap)) as client:
        created = client.post("/api/auth/create", headers={"X-Vault-Bootstrap": bootstrap, "X-Vault-Client": "vault-unified-desktop"}, json={"password": "generated-only", "confirm_password": "generated-only"})
        assert created.status_code == 200, created.text
        headers = {"X-Vault-Bootstrap": bootstrap, "Authorization": "Bearer " + created.json()["token"]}
        vault = sessions.get(created.json()["token"])
        first = vault.add("Generated A", username="generated", password="generated-a", url="https://example.invalid/login", auto_push=False)
        second = vault.add("Generated B", password="generated-b", auto_push=False)
        yield client, headers, vault, first, second
    sessions.lock_all()


def perform(client, headers, ids, action, **kwargs):
    body = {"entry_ids": ids, "action": action, **kwargs}
    preview = client.post("/api/organization/preview", headers=headers, json=body)
    assert preview.status_code == 200, preview.text
    result = client.post("/api/organization/apply", headers=headers, json={**body, "preview_token": preview.json()["preview_token"], "confirm": True})
    assert result.status_code == 200, result.text
    return preview.json()["preview_token"]


def test_bulk_archive_trash_restore_favorite_and_fill_exclusion(organized_api):
    client, headers, vault, first, second = organized_api
    assert matches_for_url(vault, first.url)
    perform(client, headers, [first.id, second.id], "archive")
    assert client.get("/api/entries", headers=headers).json() == []
    assert len(client.get("/api/entries?state=archived", headers=headers).json()) == 2
    assert matches_for_url(vault, first.url) == []
    perform(client, headers, [first.id], "restore")
    perform(client, headers, [first.id], "favorite")
    perform(client, headers, [first.id], "tag", tags=["work", "work"])
    assert client.get("/api/entries", headers=headers).json()[0]["favorite"]
    assert vault.get(first.id).tags == ["work"]
    perform(client, headers, [first.id], "trash")
    assert matches_for_url(vault, first.url) == []
    assert vault.get(first.id).password == "generated-a"
    assert organization_for(vault.get(first.id))["trashed_at"]
    perform(client, headers, [first.id], "restore")
    assert matches_for_url(vault, first.url)
    assert vault.get(first.id).password == "generated-a"
    assert UnifiedVault(vault.vault_path, "generated-only").get(first.id).tags == ["work"]


def test_previews_cancel_stale_changes_and_repeated_apply(organized_api):
    client, headers, vault, first, second = organized_api
    body = {"entry_ids": [first.id, second.id], "action": "trash"}
    before = vault.vault_path.read_bytes()
    preview = client.post("/api/organization/preview", headers=headers, json=body).json()
    assert vault.vault_path.read_bytes() == before
    assert client.post("/api/organization/cancel", headers=headers, json={"preview_token": preview["preview_token"]}).status_code == 200
    assert client.post("/api/organization/apply", headers=headers, json={**body, **preview, "confirm": True}).status_code == 409
    stale = client.post("/api/organization/preview", headers=headers, json=body).json()
    vault.local.update(first.id, notes="Changed after preview")
    assert client.post("/api/organization/apply", headers=headers, json={**body, "preview_token": stale["preview_token"], "confirm": True}).status_code == 409
    assert organization_for(vault.get(first.id))["state"] == "active"
    altered = client.post("/api/organization/preview", headers=headers, json=body).json()
    assert client.post("/api/organization/apply", headers=headers, json={**body, "action": "archive", "preview_token": altered["preview_token"], "confirm": True}).status_code == 409
    token = perform(client, headers, [first.id, second.id], "trash")
    once = vault.vault_path.read_bytes()
    assert client.post("/api/organization/apply", headers=headers, json={**body, "preview_token": token, "confirm": True}).status_code == 409
    assert vault.vault_path.read_bytes() == once


def test_batch_write_failure_preserves_all_entries(organized_api, monkeypatch):
    client, headers, vault, first, second = organized_api
    from vault_unified import local_store
    before = vault.local.export_payload()
    def fail(*args, **kwargs):
        raise OSError("generated write failure")
    body = {"entry_ids": [first.id, second.id], "action": "trash"}
    preview = client.post("/api/organization/preview", headers=headers, json=body).json()
    monkeypatch.setattr(local_store, "write_encrypted_file", fail)
    assert client.post("/api/organization/apply", headers=headers, json={**body, "preview_token": preview["preview_token"], "confirm": True}).status_code == 409
    assert vault.local.export_payload() == before
    assert decrypt_payload("generated-only", vault.vault_path.read_bytes()) == before


def test_retention_keeps_archive_and_unexpired_trash_then_removes_secret_content(tmp_path):
    path = tmp_path / "active.vault"
    create_v3_file(path, "generated-only", {"version": 3, "entries": {}, "metadata": {}})
    vault = UnifiedVault(path, "generated-only")
    now = datetime.now(timezone.utc)
    old = SecretEntry(title="Expired", password="generated-expired", notes="generated-note")
    update_data(old, totp_secret="GENERATED", custom_fields=[{"label": "secret", "value": "generated-value", "concealed": True}])
    from vault_unified.sync.ledger import AdapterCapabilities
    old.sync_ledger.replica("bitwarden", "generated-remote-id", AdapterCapabilities()).record_base(old, remote_revision="generated-revision", local_revision=old.sync_ledger.content_revision)
    old = prepare_action(old, "trash", tags=[], now=now - timedelta(days=30))
    recent = prepare_action(SecretEntry(title="Recent"), "trash", tags=[], now=now - timedelta(days=29))
    archived = prepare_action(SecretEntry(title="Archived"), "archive", tags=[])
    for entry in [old, recent, archived]:
        vault.local.commit_entry(entry, create=True)
    assert purge_expired(vault, now=now) == 1
    assert purge_expired(vault, now=now) == 0
    assert vault.get(old.id).sync_status == SyncStatus.DELETED_PENDING
    assert vault.get(old.id).password == ""
    assert vault.get(old.id).notes == ""
    assert vault.get(old.id).source_metadata == {}
    assert "generated-expired" not in str(vault.get(old.id).to_dict())
    assert organization_for(vault.get(recent.id))["state"] == "trash"
    assert organization_for(vault.get(archived.id))["state"] == "archived"


def test_external_metadata_refresh_preserves_personal_state():
    entry = prepare_action(SecretEntry(title="Generated"), "archive", tags=[])
    before = copy.deepcopy(entry.source_metadata)
    merged = merge_personal_metadata(before, {"remote": {"some": "value"}})
    assert merged[ORGANIZATION_KEY] == before[ORGANIZATION_KEY]


def test_plaintext_export_does_not_resurrect_trash_or_archive(organized_api):
    from vault_unified.transfer import export_transfer, parse_transfer
    client, headers, vault, first, second = organized_api
    perform(client, headers, [first.id], "trash")
    for format_name in ("json", "csv"):
        content, _, _ = export_transfer(vault, format_name)
        assert [entry.title for entry in parse_transfer(content, format_name)] == [second.title]
    perform(client, headers, [second.id], "archive")
    for format_name in ("json", "csv"):
        assert parse_transfer(export_transfer(vault, format_name)[0], format_name) == []

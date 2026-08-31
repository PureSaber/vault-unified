from __future__ import annotations

import base64
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("fastapi")

from vault_unified.api.app import create_app
from vault_unified.manager import UnifiedVault

BOOTSTRAP_SECRET = "test-bootstrap-secret-0123456789abcdef"


@pytest.fixture
def client(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        vault_file = Path(tmp) / "secrets.vault"
        monkeypatch.setenv("VAULT_FILE", str(vault_file))
        monkeypatch.setattr("vault_unified.config.get_vault_path", lambda: vault_file)
        UnifiedVault.create(vault_file, "test123")
        app = create_app(
            bootstrap_secret=BOOTSTRAP_SECRET,
            instance_id="test-api-entries",
        )
        with TestClient(app) as test_client:
            yield test_client


def bootstrap_headers() -> dict[str, str]:
    return {"X-Vault-Bootstrap": BOOTSTRAP_SECRET}


def unlock_headers(client: TestClient) -> dict[str, str]:
    res = client.post(
        "/api/auth/unlock",
        json={"password": "test123", "remember": False},
        headers=bootstrap_headers(),
    )
    assert res.status_code == 200
    return {
        **bootstrap_headers(),
        "Authorization": f"Bearer {res.json()['token']}",
    }


def test_unlock_and_crud(client):
    headers = unlock_headers(client)

    create = client.post(
        "/api/entries",
        json={"title": "GitHub", "username": "u", "password": "p"},
        headers=headers,
    )
    assert create.status_code == 200
    entry_id = create.json()["id"]

    listing = client.get("/api/entries", headers=headers)
    assert listing.status_code == 200
    assert len(listing.json()) == 1

    patch = client.patch(
        f"/api/entries/{entry_id}",
        json={"username": "new"},
        headers=headers,
    )
    assert patch.status_code == 200
    assert patch.json()["username"] == "new"

    delete = client.delete(f"/api/entries/{entry_id}", headers=headers)
    assert delete.status_code == 200

    after_delete = client.get("/api/entries", headers=headers)
    assert after_delete.status_code == 200
    assert after_delete.json() == []


def test_list_returns_presence_flags_without_mask_placeholders(client):
    headers = unlock_headers(client)
    create = client.post(
        "/api/entries",
        json={
            "title": "Mail",
            "password": "actual-password",
            "notes": "private notes",
        },
        headers=headers,
    )
    assert create.status_code == 200
    entry_id = create.json()["id"]

    listing = client.get("/api/entries", headers=headers)
    assert listing.status_code == 200
    item = listing.json()[0]
    assert item["password"] == ""
    assert item["notes"] == ""
    assert item["has_password"] is True
    assert item["has_notes"] is True

    revealed = client.get(
        f"/api/entries/{entry_id}?reveal=true",
        headers=headers,
    )
    assert revealed.status_code == 200
    assert revealed.json()["password"] == "actual-password"
    assert revealed.json()["notes"] == "private notes"


def test_patch_accepts_mask_like_values_and_explicit_empty_strings(client):
    headers = unlock_headers(client)
    create = client.post(
        "/api/entries",
        json={"title": "Example", "password": "old", "notes": "old notes"},
        headers=headers,
    )
    assert create.status_code == 200
    entry_id = create.json()["id"]

    literal_password = "prefix****suffix"
    literal_notes = "•• literal note"
    update = client.patch(
        f"/api/entries/{entry_id}",
        json={"password": literal_password, "notes": literal_notes},
        headers=headers,
    )
    assert update.status_code == 200
    assert update.json()["password"] == literal_password
    assert update.json()["notes"] == literal_notes

    clear = client.patch(
        f"/api/entries/{entry_id}",
        json={"password": "", "notes": ""},
        headers=headers,
    )
    assert clear.status_code == 200
    assert clear.json()["password"] == ""
    assert clear.json()["notes"] == ""
    assert clear.json()["has_password"] is False
    assert clear.json()["has_notes"] is False


def test_invalid_personal_extension_does_not_partially_persist_entry_changes(client):
    headers = unlock_headers(client)
    rejected_create = client.post(
        "/api/entries",
        json={
            "title": "Invalid extension",
            "custom_fields": [{"label": "", "value": "x", "concealed": False}],
        },
        headers=headers,
    )
    assert rejected_create.status_code == 400
    assert client.get("/api/entries", headers=headers).json() == []

    created = client.post(
        "/api/entries",
        json={"title": "Original", "username": "before", "password": "secret"},
        headers=headers,
    )
    assert created.status_code == 200
    rejected_patch = client.patch(
        f"/api/entries/{created.json()['id']}",
        json={
            "title": "Should not save",
            "custom_fields": [{"label": "", "value": "x", "concealed": False}],
        },
        headers=headers,
    )
    assert rejected_patch.status_code == 400
    unchanged = client.get(f"/api/entries/{created.json()['id']}?reveal=true", headers=headers)
    assert unchanged.status_code == 200
    assert unchanged.json()["title"] == "Original"
    assert unchanged.json()["username"] == "before"


def _transaction(entry: dict, transaction_id: str, **overrides) -> dict:
    value = {
        "transaction_id": transaction_id,
        "entry_id": entry["id"],
        "expected_updated_at": entry["updated_at"],
        "title": entry["title"],
        "username": entry["username"],
        "password": entry["password"],
        "url": entry["url"],
        "notes": entry["notes"],
        "tags": entry["tags"],
        "entry_type": entry["entry_type"],
        "custom_fields": entry["custom_fields"],
        "totp_secret": entry["totp_secret"],
        "add_attachments": [],
        "remove_attachment_ids": [],
        "restore_history_id": None,
    }
    value.update(overrides)
    return value


def test_editor_transaction_is_idempotent_and_rejects_stale_generation(client):
    headers = unlock_headers(client)
    created = client.post(
        "/api/entries",
        json={"title": "Generated account", "password": "generated-secret"},
        headers=headers,
    ).json()
    payload = _transaction(
        created,
        "generated-transaction-0001",
        username="updated-user",
    )

    first = client.post("/api/entries/commit", json=payload, headers=headers)
    assert first.status_code == 200
    replay = client.post("/api/entries/commit", json=payload, headers=headers)
    assert replay.status_code == 200
    assert replay.json()["id"] == first.json()["id"]
    assert replay.json()["history_count"] == first.json()["history_count"] == 1

    stale = client.post(
        "/api/entries/commit",
        json={**payload, "transaction_id": "generated-transaction-0002"},
        headers=headers,
    )
    assert stale.status_code == 409
    assert "reload" in stale.json()["detail"].lower()


def test_attachment_batch_failure_leaves_file_and_memory_unchanged(
    client,
    monkeypatch,
):
    headers = unlock_headers(client)
    created = client.post(
        "/api/entries",
        json={"title": "Attachment transaction", "password": "generated-secret"},
        headers=headers,
    ).json()
    vault_path = Path(client.get("/api/auth/vault-info", headers=headers).json()["path"])
    before_bytes = vault_path.read_bytes()
    payload = _transaction(
        created,
        "generated-attachment-transaction",
        title="Must not partially save",
        add_attachments=[
            {
                "filename": f"generated-{index}.txt",
                "mime_type": "text/plain",
                "data_b64": base64.b64encode(f"generated-{index}".encode()).decode(),
            }
            for index in range(3)
        ],
    )

    from vault_unified import manager as manager_module

    real_add_attachment = manager_module.add_attachment
    calls = 0

    def fail_third(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise RuntimeError("generated attachment failure")
        return real_add_attachment(*args, **kwargs)

    with monkeypatch.context() as scoped:
        scoped.setattr(manager_module, "add_attachment", fail_third)
        failed = client.post("/api/entries/commit", json=payload, headers=headers)

    assert failed.status_code == 500
    assert failed.json()["detail"] == "Entry was not saved; no changes were committed"
    assert vault_path.read_bytes() == before_bytes
    unchanged = client.get(f"/api/entries/{created['id']}?reveal=true", headers=headers).json()
    assert unchanged["title"] == "Attachment transaction"
    assert unchanged["attachments"] == []


def test_encrypted_write_failure_leaves_file_and_memory_unchanged(client, monkeypatch):
    headers = unlock_headers(client)
    created = client.post(
        "/api/entries",
        json={"title": "Before failed write", "password": "generated-secret"},
        headers=headers,
    ).json()
    vault_path = Path(client.get("/api/auth/vault-info", headers=headers).json()["path"])
    before_bytes = vault_path.read_bytes()

    def fail_write(*_args, **_kwargs):
        raise OSError("generated atomic write failure")

    with monkeypatch.context() as scoped:
        scoped.setattr("vault_unified.local_store.write_encrypted_file", fail_write)
        failed = client.post(
            "/api/entries/commit",
            json=_transaction(
                created,
                "generated-write-failure-transaction",
                title="Must remain unchanged",
            ),
            headers=headers,
        )

    assert failed.status_code == 500
    assert failed.json()["detail"] == "Entry was not saved; no changes were committed"
    assert vault_path.read_bytes() == before_bytes
    unchanged = client.get(f"/api/entries/{created['id']}?reveal=true", headers=headers).json()
    assert unchanged["title"] == "Before failed write"


def test_history_preview_is_read_only_and_restore_commits_with_draft(client):
    headers = unlock_headers(client)
    created = client.post(
        "/api/entries",
        json={
            "title": "Original version",
            "username": "original-user",
            "password": "generated-original-secret",
        },
        headers=headers,
    ).json()
    updated = client.post(
        "/api/entries/commit",
        json=_transaction(
            created,
            "generated-history-update",
            title="Current version",
            username="current-user",
            password="generated-current-secret",
        ),
        headers=headers,
    ).json()
    history = client.get(f"/api/entries/{created['id']}/history", headers=headers).json()["history"]
    history_id = history[0]["id"]
    vault_path = Path(client.get("/api/auth/vault-info", headers=headers).json()["path"])
    before_preview = vault_path.read_bytes()

    preview = client.get(
        f"/api/entries/{created['id']}/history/{history_id}",
        headers=headers,
    )
    assert preview.status_code == 200
    assert preview.json()["entry"]["title"] == "Original version"
    assert vault_path.read_bytes() == before_preview
    current = client.get(f"/api/entries/{created['id']}?reveal=true", headers=headers).json()
    assert current["title"] == "Current version"

    draft = preview.json()["entry"]
    restored = client.post(
        "/api/entries/commit",
        json=_transaction(
            updated,
            "generated-history-restore",
            title=draft["title"],
            username=draft["username"],
            password=draft["password"],
            restore_history_id=history_id,
        ),
        headers=headers,
    )
    assert restored.status_code == 200
    assert restored.json()["title"] == "Original version"
    assert restored.json()["username"] == "original-user"


def test_legacy_history_restore_endpoint_refuses_immediate_write(client):
    headers = unlock_headers(client)
    created = client.post(
        "/api/entries",
        json={"title": "Original", "password": "generated-secret"},
        headers=headers,
    ).json()
    updated = client.patch(
        f"/api/entries/{created['id']}",
        json={"title": "Current"},
        headers=headers,
    ).json()
    history_id = client.get(
        f"/api/entries/{created['id']}/history",
        headers=headers,
    ).json()["history"][0]["id"]
    refused = client.post(
        f"/api/entries/{created['id']}/history/{history_id}/restore",
        headers=headers,
    )
    assert refused.status_code == 409
    current = client.get(f"/api/entries/{created['id']}?reveal=true", headers=headers).json()
    assert current["title"] == updated["title"] == "Current"

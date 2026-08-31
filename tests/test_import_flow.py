from __future__ import annotations

import base64
import hashlib
import json
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("fastapi")

from vault_unified.api.app import create_app
from vault_unified.backup_manager import list_backups
from vault_unified.manager import UnifiedVault
from vault_unified.session import sessions


BOOTSTRAP_SECRET = "generated-import-bootstrap-0123456789abcdef"
PASSWORD = "generated-test-master-password"
ENTRY_PASSWORD = "generated-entry-password-never-return"
TOTP_SECRET = "JBSWY3DPEHPK3PXP"


@pytest.fixture
def api_client(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        vault_file = root / "active" / "secrets.vault"
        monkeypatch.setenv("VAULT_FILE", str(vault_file))
        monkeypatch.setenv("VAULT_CONFIG_DIR", str(root / "config"))
        monkeypatch.setattr("vault_unified.config.get_vault_path", lambda: vault_file)
        UnifiedVault.create(vault_file, PASSWORD)
        app = create_app(
            bootstrap_secret=BOOTSTRAP_SECRET,
            instance_id="generated-import-flow-test",
        )
        with TestClient(app) as client:
            yield client, vault_file
        sessions.lock_all()


def _bootstrap() -> dict[str, str]:
    return {"X-Vault-Bootstrap": BOOTSTRAP_SECRET}


def _unlock(client: TestClient) -> tuple[dict[str, str], str]:
    response = client.post(
        "/api/auth/unlock",
        json={"password": PASSWORD, "remember": False},
        headers=_bootstrap(),
    )
    assert response.status_code == 200
    token = response.json()["token"]
    return {**_bootstrap(), "Authorization": f"Bearer {token}"}, token


def _create_entry(
    client: TestClient,
    headers: dict[str, str],
    *,
    title: str,
    username: str,
    password: str,
    url: str,
) -> dict:
    response = client.post(
        "/api/entries/commit",
        json={
            "transaction_id": f"generated-create-{title}-00000000",
            "entry_id": None,
            "expected_updated_at": None,
            "title": title,
            "username": username,
            "password": password,
            "url": url,
            "notes": "generated existing note",
            "tags": [],
            "entry_type": "login",
            "custom_fields": [],
            "totp_secret": "",
            "add_attachments": [],
            "remove_attachment_ids": [],
            "restore_history_id": None,
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _json_transfer(entries: list[dict]) -> str:
    return json.dumps(
        {"schema": "vault-unified-transfer", "version": 1, "entries": entries},
        ensure_ascii=False,
    )


def _item(
    title: str,
    *,
    username: str = "generated-user",
    password: str = ENTRY_PASSWORD,
    url: str = "https://example.test/login",
    notes: str = "generated note never returned",
) -> dict:
    return {
        "title": title,
        "username": username,
        "password": password,
        "url": url,
        "notes": notes,
        "tags": ["generated"],
        "entry_type": "login",
        "custom_fields": [
            {"label": "generated field", "value": "generated custom secret", "concealed": True}
        ],
        "totp_secret": TOTP_SECRET,
        "attachments": [],
    }


def _preview(
    client: TestClient,
    headers: dict[str, str],
    content: str,
    format_name: str = "json",
):
    return client.post(
        "/api/transfer/import/preview",
        json={
            "format": format_name,
            "content": content,
            "confirm_plaintext": True,
        },
        headers=headers,
    )


def test_preview_is_read_only_classifies_duplicates_and_returns_no_secrets(api_client) -> None:
    client, vault_path = api_client
    headers, _ = _unlock(client)
    _create_entry(
        client,
        headers,
        title="Existing",
        username="generated-user",
        password=ENTRY_PASSWORD,
        url="https://example.test/login",
    )
    before = vault_path.read_bytes()
    content = _json_transfer(
        [
            {
                **_item("Existing"),
                "notes": "generated existing note",
                "tags": [],
                "custom_fields": [],
                "totp_secret": "",
            },
            _item("Renamed", password="generated-different-password"),
            _item("全新账号", username="中文用户", url="https://例子.测试/登录"),
            {**_item("Unsupported"), "future_secret_field": "must never be returned"},
        ]
    )

    response = _preview(client, headers, content)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["counts"] == {
        "total": 4,
        "importable": 2,
        "exact_duplicates": 1,
        "possible_duplicates": 1,
        "format_errors": 1,
        "skipped": 3,
        "add": 1,
        "update": 0,
        "unsupported_fields": 1,
        "attachments": 0,
        "attachment_bytes": 0,
    }
    rendered = response.text
    for secret in (
        ENTRY_PASSWORD,
        "generated-different-password",
        TOTP_SECRET,
        "generated note never returned",
        "generated custom secret",
        "must never be returned",
    ):
        assert secret not in rendered
    assert vault_path.read_bytes() == before

    cancelled = client.post(
        "/api/transfer/import/cancel",
        json={"preview_token": payload["preview_token"]},
        headers=headers,
    )
    assert cancelled.status_code == 200
    refused = client.post(
        "/api/transfer/import/apply",
        json={"preview_token": payload["preview_token"], "decisions": []},
        headers=headers,
    )
    assert refused.status_code == 409
    assert vault_path.read_bytes() == before


def test_apply_is_single_write_receipt_has_no_secrets_and_undo_is_exact(api_client, monkeypatch) -> None:
    client, vault_path = api_client
    headers, token = _unlock(client)
    existing = _create_entry(
        client,
        headers,
        title="Old title",
        username="same-user",
        password="generated-old-password",
        url="https://same.example/login",
    )
    vault = sessions.get(token)
    before_digest = vault.local.state_digest()
    content = _json_transfer(
        [
            _item(
                "Updated title",
                username="same-user",
                password=ENTRY_PASSWORD,
                url="https://same.example/account",
            ),
            _item("New imported entry", username="new-user", url="https://new.example/login"),
        ]
    )
    preview = _preview(client, headers, content)
    assert preview.status_code == 200, preview.text
    possible = next(
        item for item in preview.json()["items"] if item["classification"] == "possible_duplicate"
    )

    original_save = vault.local._save_entries
    writes = 0

    def counted_save(entries):
        nonlocal writes
        writes += 1
        return original_save(entries)

    monkeypatch.setattr(vault.local, "_save_entries", counted_save)
    applied = client.post(
        "/api/transfer/import/apply",
        json={
            "preview_token": preview.json()["preview_token"],
            "decisions": [
                {
                    "preview_id": possible["preview_id"],
                    "action": "update",
                    "target_entry_id": existing["id"],
                }
            ],
        },
        headers=headers,
    )
    assert applied.status_code == 200, applied.text
    assert writes == 1
    result = applied.json()
    assert result["added"] == 1
    assert result["updated"] == 1
    receipt_text = json.dumps(result["receipt"])
    for secret in (ENTRY_PASSWORD, TOTP_SECRET, "generated custom secret", "generated note never returned"):
        assert secret not in receipt_text
    assert result["receipt"]["before_vault_digest"] == before_digest
    assert vault.local.state_digest() == result["receipt"]["after_vault_digest"]
    backups = list_backups(vault_path, vault.local.credential)
    assert len([backup for backup in backups if backup.kind == "manual" and backup.verified]) == 1

    replay = client.post(
        "/api/transfer/import/apply",
        json={"preview_token": preview.json()["preview_token"], "decisions": []},
        headers=headers,
    )
    assert replay.status_code == 409
    assert writes == 1

    undone = client.post(
        "/api/transfer/import/undo",
        json={"transaction_id": result["receipt"]["transaction_id"]},
        headers=headers,
    )
    assert undone.status_code == 200, undone.text
    assert writes == 2
    assert vault.local.state_digest() == before_digest
    entries = client.get("/api/entries", headers=headers).json()
    assert [entry["title"] for entry in entries] == ["Old title"]
    assert client.post(
        "/api/transfer/import/undo",
        json={"transaction_id": result["receipt"]["transaction_id"]},
        headers=headers,
    ).status_code == 409


def test_undo_is_refused_after_a_later_edit(api_client) -> None:
    client, _ = api_client
    headers, _ = _unlock(client)
    preview = _preview(client, headers, _json_transfer([_item("Imported once")]))
    applied = client.post(
        "/api/transfer/import/apply",
        json={"preview_token": preview.json()["preview_token"], "decisions": []},
        headers=headers,
    )
    assert applied.status_code == 200, applied.text
    _create_entry(
        client,
        headers,
        title="Later edit",
        username="later-user",
        password="generated-later-password",
        url="https://later.example",
    )
    refused = client.post(
        "/api/transfer/import/undo",
        json={"transaction_id": applied.json()["receipt"]["transaction_id"]},
        headers=headers,
    )
    assert refused.status_code == 409
    titles = [entry["title"] for entry in client.get("/api/entries", headers=headers).json()]
    assert titles == ["Imported once", "Later edit"]


def test_mid_apply_failure_leaves_vault_bytes_and_memory_unchanged(api_client, monkeypatch) -> None:
    client, vault_path = api_client
    headers, token = _unlock(client)
    vault = sessions.get(token)
    preview = _preview(client, headers, _json_transfer([_item("Atomic failure")]))
    before_bytes = vault_path.read_bytes()
    before_digest = vault.local.state_digest()
    before_generation = vault.local.generation

    def fail_save(entries):
        _ = entries
        raise OSError("generated injected encrypted-write failure")

    monkeypatch.setattr(vault.local, "_save_entries", fail_save)
    failed = client.post(
        "/api/transfer/import/apply",
        json={"preview_token": preview.json()["preview_token"], "decisions": []},
        headers=headers,
    )
    assert failed.status_code == 500
    assert "generated injected" not in failed.text
    assert vault_path.read_bytes() == before_bytes
    assert vault.local.state_digest() == before_digest
    assert vault.local.generation == before_generation
    assert vault.local.list_entries() == []


def test_csv_quotes_newlines_chinese_invalid_json_and_direct_import_are_safe(api_client) -> None:
    client, vault_path = api_client
    headers, _ = _unlock(client)
    csv_content = (
        'title,username,password,url,notes,tags,entry_type,custom_fields,totp_secret\r\n'
        '"中文, 账号","用户""名",generated-csv-password,https://csv.example,"第一行\n第二行","中文|测试",login,[],\r\n'
        'Invalid custom fields,user,generated-invalid-row,https://invalid.example,note,,login,not-json,\r\n'
    )
    preview = _preview(client, headers, csv_content, "csv")
    assert preview.status_code == 200, preview.text
    assert preview.json()["counts"]["total"] == 2
    assert preview.json()["counts"]["format_errors"] == 1
    assert preview.json()["items"][0]["title"] == "中文, 账号"
    assert preview.json()["items"][0]["username"] == '用户"名'
    assert "generated-csv-password" not in preview.text
    applied = client.post(
        "/api/transfer/import/apply",
        json={"preview_token": preview.json()["preview_token"], "decisions": []},
        headers=headers,
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["skipped"] == 1
    entry_id = applied.json()["receipt"]["added_entry_ids"][0]
    revealed = client.get(f"/api/entries/{entry_id}?reveal=true", headers=headers).json()
    assert revealed["notes"] == "第一行\n第二行"

    before = vault_path.read_bytes()
    invalid = _preview(client, headers, "{invalid json")
    assert invalid.status_code == 400
    assert vault_path.read_bytes() == before
    duplicate_secret = "generated-duplicate-json-secret"
    duplicate_json = (
        '{"schema":"vault-unified-transfer","version":1,"entries":['
        '{"title":"Duplicate field","password":"first","password":"'
        + duplicate_secret
        + '"}]}'
    )
    duplicate = _preview(client, headers, duplicate_json)
    assert duplicate.status_code == 400
    assert duplicate_secret not in duplicate.text
    assert vault_path.read_bytes() == before
    direct = client.post(
        "/api/transfer/import",
        json={"format": "json", "content": _json_transfer([_item("Blocked")]), "confirm_plaintext": True},
        headers=headers,
    )
    assert direct.status_code == 409
    assert vault_path.read_bytes() == before


def test_attachment_preview_returns_only_count_size_and_digest_is_source_hash(api_client) -> None:
    client, _ = api_client
    headers, _ = _unlock(client)
    attachment_bytes = b"generated attachment content"
    encoded = base64.b64encode(attachment_bytes).decode("ascii")
    item = _item("Attachment")
    item["attachments"] = [
        {
            "id": "generated-attachment-id",
            "filename": "generated.txt",
            "mime_type": "text/plain",
            "size": len(attachment_bytes),
            "sha256": hashlib.sha256(attachment_bytes).hexdigest(),
            "data_b64": encoded,
        }
    ]
    content = _json_transfer([item])
    preview = _preview(client, headers, content)
    assert preview.status_code == 200, preview.text
    assert preview.json()["counts"]["attachments"] == 1
    assert preview.json()["counts"]["attachment_bytes"] == len(attachment_bytes)
    assert preview.json()["source_file_digest"] == hashlib.sha256(content.encode("utf-8")).hexdigest()
    assert encoded not in preview.text


def test_url_path_case_is_not_an_exact_duplicate_and_stale_preview_is_refused(api_client) -> None:
    client, _ = api_client
    headers, _ = _unlock(client)
    _create_entry(
        client,
        headers,
        title="Case-sensitive URL",
        username="case-user",
        password=ENTRY_PASSWORD,
        url="https://case.example/Account",
    )
    item = _item(
        "Case-sensitive URL",
        username="case-user",
        password=ENTRY_PASSWORD,
        url="https://case.example/account",
        notes="generated existing note",
    )
    item["tags"] = []
    item["custom_fields"] = []
    item["totp_secret"] = ""
    preview = _preview(client, headers, _json_transfer([item]))
    assert preview.status_code == 200, preview.text
    assert preview.json()["counts"]["exact_duplicates"] == 0
    assert preview.json()["counts"]["possible_duplicates"] == 1

    _create_entry(
        client,
        headers,
        title="Later state change",
        username="later-state-user",
        password="generated-later-state-password",
        url="https://later-state.example",
    )
    refused = client.post(
        "/api/transfer/import/apply",
        json={"preview_token": preview.json()["preview_token"], "decisions": []},
        headers=headers,
    )
    assert refused.status_code == 409
    titles = [entry["title"] for entry in client.get("/api/entries", headers=headers).json()]
    assert "Case-sensitive URL" in titles
    assert "Later state change" in titles


def test_malformed_url_is_previewed_without_crashing_or_echoing_secrets(api_client) -> None:
    client, _ = api_client
    headers, _ = _unlock(client)
    secret = "generated-malformed-url-password"
    item = _item(
        "Malformed URL",
        username="malformed-user",
        password=secret,
        url="https://[invalid-ipv6",
    )
    preview = _preview(client, headers, _json_transfer([item]))
    assert preview.status_code == 200, preview.text
    assert preview.json()["counts"]["add"] == 1
    assert preview.json()["items"][0]["host"] == ""
    assert secret not in preview.text


def test_duplicates_inside_one_file_import_only_once_by_default(api_client) -> None:
    client, _ = api_client
    headers, _ = _unlock(client)
    duplicate = _item("Repeated in file", username="repeat-user")
    preview = _preview(client, headers, _json_transfer([duplicate, duplicate]))
    assert preview.status_code == 200, preview.text
    assert preview.json()["counts"]["add"] == 1
    assert preview.json()["counts"]["exact_duplicates"] == 1
    applied = client.post(
        "/api/transfer/import/apply",
        json={"preview_token": preview.json()["preview_token"], "decisions": []},
        headers=headers,
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["added"] == 1
    assert applied.json()["skipped"] == 1
    assert len(client.get("/api/entries", headers=headers).json()) == 1


def test_two_rows_cannot_update_the_same_target_or_create_a_backup(api_client) -> None:
    client, vault_path = api_client
    headers, token = _unlock(client)
    existing = _create_entry(
        client,
        headers,
        title="One update target",
        username="shared-user",
        password="generated-original-target-password",
        url="https://shared.example/login",
    )
    vault = sessions.get(token)
    rows = [
        _item(
            "Candidate one",
            username="shared-user",
            password="generated-candidate-one",
            url="https://shared.example/one",
        ),
        _item(
            "Candidate two",
            username="shared-user",
            password="generated-candidate-two",
            url="https://shared.example/two",
        ),
    ]
    preview = _preview(client, headers, _json_transfer(rows))
    assert preview.status_code == 200, preview.text
    decisions = [
        {
            "preview_id": item["preview_id"],
            "action": "update",
            "target_entry_id": existing["id"],
        }
        for item in preview.json()["items"]
    ]
    before = vault_path.read_bytes()
    rejected = client.post(
        "/api/transfer/import/apply",
        json={"preview_token": preview.json()["preview_token"], "decisions": decisions},
        headers=headers,
    )
    assert rejected.status_code == 400
    assert vault_path.read_bytes() == before
    assert [backup for backup in list_backups(vault_path, vault.local.credential) if backup.kind == "manual"] == []

from __future__ import annotations

import copy
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("fastapi")

from vault_unified.api.app import create_app
from vault_unified.local_store import LocalVault
from vault_unified.manager import MetadataPreservingSyncEngine
from vault_unified.models import SecretEntry, Source, SyncPreferences
from vault_unified.session import sessions
from vault_unified.sync.ledger import AdapterCapabilities
from vault_unified.sync.preview import (
    SyncPreviewExpired,
    SyncPreviewStore,
    preview_store,
)
from vault_unified.sync_prefs import save_prefs


BOOTSTRAP_SECRET = "sync-preview-test-secret-0123456789abcdef"


class FakeBitwarden:
    name = "Bitwarden"
    source = Source.BITWARDEN
    capabilities = AdapterCapabilities(
        authoritative_list=True,
        revision_token=True,
        idempotent_create=False,
        delete_confirm=True,
        absence_is_delete=False,
    )

    def __init__(self) -> None:
        self.entries: dict[str, SecretEntry] = {}
        self.create_calls = 0
        self.update_calls = 0
        self.delete_calls = 0
        self.available = True

    def is_configured(self) -> bool:
        return True

    def is_available(self) -> bool:
        return self.available

    def list_entries(self) -> list[SecretEntry]:
        return [copy.deepcopy(entry) for entry in self.entries.values()]

    def get_entry(self, external_id: str) -> SecretEntry | None:
        value = self.entries.get(external_id)
        return copy.deepcopy(value) if value else None

    def create_entry(
        self,
        entry: SecretEntry,
        *,
        operation_id: str | None = None,
    ) -> SecretEntry:
        assert operation_id
        self.create_calls += 1
        external_id = f"bw-{self.create_calls}"
        remote = copy.deepcopy(entry)
        remote.external_id = external_id
        remote.link_source(Source.BITWARDEN, external_id)
        remote.remote_updated_at = f"revision-{self.create_calls}"
        self.entries[external_id] = remote
        return copy.deepcopy(remote)

    def update_entry(
        self,
        entry: SecretEntry,
        *,
        operation_id: str | None = None,
    ) -> SecretEntry:
        assert operation_id
        self.update_calls += 1
        external_id = entry.get_linked_id(Source.BITWARDEN)
        self.entries[external_id] = copy.deepcopy(entry)
        return copy.deepcopy(entry)

    def delete_entry(
        self,
        external_id: str,
        *,
        permanent: bool = False,
        operation_id: str | None = None,
    ) -> None:
        assert operation_id
        self.delete_calls += 1
        self.entries.pop(external_id, None)


def test_preview_is_read_only_and_digest_is_stable(tmp_path: Path) -> None:
    vault_path = tmp_path / "preview.vault"
    local = LocalVault.create(vault_path, "generated-preview-password")
    save_prefs(
        vault_path,
        SyncPreferences(enabled_sources=["bitwarden"]),
    )
    local.add(
        SecretEntry(
            title="Local only",
            username="local-user",
            password="local-password",
        )
    )

    vault = MagicMock()
    vault.local = local
    vault.vault_path = vault_path
    vault._last_errors = []
    engine = MetadataPreservingSyncEngine(vault)
    vault.sync = engine

    adapter = MagicMock()
    adapter.name = "Bitwarden"
    adapter.capabilities = FakeBitwarden.capabilities
    adapter.is_configured.return_value = True
    adapter.is_available.return_value = True

    def fresh_remote() -> list[SecretEntry]:
        remote = SecretEntry(
            title="Remote only",
            username="remote-user",
            password="remote-password",
            source=Source.BITWARDEN,
            external_id="remote-1",
            remote_updated_at="revision-1",
        )
        remote.link_source(Source.BITWARDEN, "remote-1")
        return [remote]

    adapter.list_entries.side_effect = fresh_remote
    before_bytes = vault_path.read_bytes()
    before_entries = [
        item.to_dict()
        for item in local.list_entries(include_deleted=True)
    ]

    with patch("vault_unified.manager.get_adapter", return_value=adapter):
        first = engine.preview_explicit(
            [Source.BITWARDEN],
            include_pull=True,
            include_push=True,
        )
        second = engine.preview_explicit(
            [Source.BITWARDEN],
            include_pull=True,
            include_push=True,
        )

    assert first["totals"]["pull_add"] == 1
    assert first["totals"]["push_create"] == 1
    assert len(first["operations"]) == 2
    assert {
        (operation["direction"], operation["action"])
        for operation in first["operations"]
    } == {("pull", "add"), ("push", "add")}
    rendered = json.dumps(first, ensure_ascii=False)
    assert "local-password" not in rendered
    assert "remote-password" not in rendered
    assert "local-user" not in rendered
    assert "remote-user" not in rendered
    assert first["_state_digest"] == second["_state_digest"]
    assert vault_path.read_bytes() == before_bytes
    assert [
        item.to_dict()
        for item in local.list_entries(include_deleted=True)
    ] == before_entries
    adapter.create_entry.assert_not_called()
    adapter.update_entry.assert_not_called()
    adapter.delete_entry.assert_not_called()


def test_preview_tokens_are_single_use_and_expire() -> None:
    now = [100.0]
    store = SyncPreviewStore(ttl_seconds=5, clock=lambda: now[0])
    issued = store.issue(
        session_token="session-a",
        sources=("bitwarden",),
        include_pull=True,
        include_push=False,
        local_fingerprint="local",
        plan_digest="remote",
        operation_digest="operations",
    )
    consumed = store.consume(issued.token, session_token="session-a")
    assert consumed == issued
    with pytest.raises(SyncPreviewExpired):
        store.consume(issued.token, session_token="session-a")

    expired = store.issue(
        session_token="session-a",
        sources=("bitwarden",),
        include_pull=False,
        include_push=True,
        local_fingerprint="local",
        plan_digest="remote",
        operation_digest="operations",
    )
    now[0] += 6
    with pytest.raises(SyncPreviewExpired):
        store.consume(expired.token, session_token="session-a")


@pytest.fixture
def api_client(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        vault_path = Path(tmp) / "secrets.vault"
        monkeypatch.setenv("VAULT_FILE", str(vault_path))
        LocalVault.create(vault_path, "test-password")
        save_prefs(
            vault_path,
            SyncPreferences(enabled_sources=["bitwarden"]),
        )
        sessions._sessions.clear()
        preview_store._intents.clear()
        app = create_app(
            bootstrap_secret=BOOTSTRAP_SECRET,
            instance_id="sync-preview-api-test",
        )
        with TestClient(app) as client:
            yield client, vault_path
        sessions._sessions.clear()
        preview_store._intents.clear()


def _headers(token: str | None = None) -> dict[str, str]:
    value = {
        "X-Vault-Bootstrap": BOOTSTRAP_SECRET,
        "X-Vault-Client": "vault-unified-desktop",
    }
    if token:
        value["Authorization"] = f"Bearer {token}"
    return value


def _unlock(client: TestClient) -> str:
    response = client.post(
        "/api/auth/unlock",
        json={"password": "test-password", "remember": False},
        headers=_headers(),
    )
    assert response.status_code == 200
    return response.json()["token"]


def test_api_requires_preview_and_invalidates_it_after_local_change(
    api_client,
) -> None:
    client, _ = api_client
    adapter = FakeBitwarden()
    token = _unlock(client)

    with (
        patch("vault_unified.manager.get_adapter", return_value=adapter),
        patch("vault_unified.sync.engine.get_adapter", return_value=adapter),
    ):
        direct = client.post("/api/sync/push", headers=_headers(token))
        assert direct.status_code == 409

        preview = client.post(
            "/api/sync/preview",
            json={
                "include_pull": False,
                "include_push": True,
                "sources": ["bitwarden"],
            },
            headers=_headers(token),
        )
        assert preview.status_code == 200
        preview_token = preview.json()["preview_token"]

        created = client.post(
            "/api/entries",
            json={
                "title": "Changed after preview",
                "username": "user",
                "password": "secret",
            },
            headers=_headers(token),
        )
        assert created.status_code == 200

        execute = client.post(
            "/api/sync/execute",
            json={"preview_token": preview_token},
            headers=_headers(token),
        )
        assert execute.status_code == 409
        assert adapter.create_calls == 0


def test_api_executes_unchanged_preview_once(api_client) -> None:
    client, _ = api_client
    adapter = FakeBitwarden()
    token = _unlock(client)

    created = client.post(
        "/api/entries",
        json={
            "title": "Ready to sync",
            "username": "user",
            "password": "secret",
        },
        headers=_headers(token),
    )
    assert created.status_code == 200

    with (
        patch("vault_unified.manager.get_adapter", return_value=adapter),
        patch("vault_unified.sync.engine.get_adapter", return_value=adapter),
    ):
        preview = client.post(
            "/api/sync/preview",
            json={
                "include_pull": False,
                "include_push": True,
                "sources": ["bitwarden"],
            },
            headers=_headers(token),
        )
        assert preview.status_code == 200
        payload = preview.json()
        assert payload["totals"]["push_create"] == 1
        assert len(payload["operations"]) == 1
        approved_id = payload["operations"][0]["operation_id"]
        assert payload["operations"][0]["title"] == "Ready to sync"
        assert payload["operations"][0]["username_display"] == "u***r"
        assert "secret" not in json.dumps(payload)

        first = client.post(
            "/api/sync/execute",
            json={"preview_token": payload["preview_token"]},
            headers=_headers(token),
        )
        assert first.status_code == 200
        assert first.json()["pushed"]["pushed"] == 1
        assert [
            operation["operation_id"]
            for operation in first.json()["operations"]
        ] == [approved_id]
        assert first.json()["operations"][0]["status"] == "completed"
        assert adapter.create_calls == 1

        second = client.post(
            "/api/sync/execute",
            json={"preview_token": payload["preview_token"]},
            headers=_headers(token),
        )
        assert second.status_code == 409
        assert adapter.create_calls == 1


def test_remote_state_change_invalidates_item_level_preview(api_client) -> None:
    client, _ = api_client
    adapter = FakeBitwarden()
    token = _unlock(client)

    with (
        patch("vault_unified.manager.get_adapter", return_value=adapter),
        patch("vault_unified.sync.engine.get_adapter", return_value=adapter),
    ):
        preview = client.post(
            "/api/sync/preview",
            json={
                "include_pull": True,
                "include_push": False,
                "sources": ["bitwarden"],
            },
            headers=_headers(token),
        )
        assert preview.status_code == 200

        remote = SecretEntry(
            title="Appeared after preview",
            username="later@example.test",
            password="generated-later-secret",
            source=Source.BITWARDEN,
            external_id="remote-later",
            remote_updated_at="revision-later",
        )
        remote.link_source(Source.BITWARDEN, "remote-later")
        adapter.entries["remote-later"] = remote

        execute = client.post(
            "/api/sync/execute",
            json={"preview_token": preview.json()["preview_token"]},
            headers=_headers(token),
        )
        assert execute.status_code == 409
        assert "Remote sync state changed" in execute.json()["detail"]


def test_remote_delete_preview_names_exact_item_and_execution_result(
    api_client,
) -> None:
    client, _ = api_client
    adapter = FakeBitwarden()
    token = _unlock(client)
    created = client.post(
        "/api/entries",
        json={
            "title": "Delete from service",
            "username": "delete.user@example.test",
            "password": "generated-delete-secret",
            "url": "https://Accounts.Example.test/private?token=hidden",
        },
        headers=_headers(token),
    )
    assert created.status_code == 200

    with (
        patch("vault_unified.manager.get_adapter", return_value=adapter),
        patch("vault_unified.sync.engine.get_adapter", return_value=adapter),
    ):
        initial = client.post(
            "/api/sync/preview",
            json={
                "include_pull": False,
                "include_push": True,
                "sources": ["bitwarden"],
            },
            headers=_headers(token),
        )
        synced = client.post(
            "/api/sync/execute",
            json={"preview_token": initial.json()["preview_token"]},
            headers=_headers(token),
        )
        assert synced.status_code == 200

        deleted = client.delete(
            f"/api/entries/{created.json()['id']}",
            headers=_headers(token),
        )
        assert deleted.status_code == 200
        preview = client.post(
            "/api/sync/preview",
            json={
                "include_pull": False,
                "include_push": True,
                "sources": ["bitwarden"],
            },
            headers=_headers(token),
        )
        assert preview.status_code == 200
        payload = preview.json()
        deletion = payload["operations"][0]
        assert deletion["action"] == "delete"
        assert deletion["deletion_side"] == "connected_service"
        assert deletion["title"] == "Delete from service"
        assert deletion["username_display"] == "d***@example.test"
        assert deletion["website_host"] == "accounts.example.test"
        assert deletion["destructive"] is True
        assert "generated-delete-secret" not in json.dumps(payload)
        assert "token=hidden" not in json.dumps(payload)

        execute = client.post(
            "/api/sync/execute",
            json={"preview_token": payload["preview_token"]},
            headers=_headers(token),
        )
        assert execute.status_code == 200
        outcome = execute.json()["operations"][0]
        assert outcome["operation_id"] == deletion["operation_id"]
        assert outcome["status"] == "completed"
        assert adapter.delete_calls == 1


def test_update_preview_lists_only_field_names_and_safe_display(api_client) -> None:
    client, _ = api_client
    adapter = FakeBitwarden()
    remote = SecretEntry(
        title="Updated account",
        username="full.user@example.test",
        password="generated-before-update-secret",
        url="https://accounts.example.test/old?private=before",
        notes="generated private note before",
        source=Source.BITWARDEN,
        external_id="remote-update",
        remote_updated_at="revision-before",
    )
    remote.link_source(Source.BITWARDEN, "remote-update")
    adapter.entries["remote-update"] = remote
    token = _unlock(client)

    with (
        patch("vault_unified.manager.get_adapter", return_value=adapter),
        patch("vault_unified.sync.engine.get_adapter", return_value=adapter),
    ):
        initial = client.post(
            "/api/sync/preview",
            json={
                "include_pull": True,
                "include_push": False,
                "sources": ["bitwarden"],
            },
            headers=_headers(token),
        )
        pulled = client.post(
            "/api/sync/execute",
            json={"preview_token": initial.json()["preview_token"]},
            headers=_headers(token),
        )
        assert pulled.status_code == 200

        changed = copy.deepcopy(adapter.entries["remote-update"])
        changed.password = "generated-after-update-secret"
        changed.url = "https://accounts.example.test/new?private=after"
        changed.notes = "generated private note after"
        changed.remote_updated_at = "revision-after"
        adapter.entries["remote-update"] = changed
        preview = client.post(
            "/api/sync/preview",
            json={
                "include_pull": True,
                "include_push": False,
                "sources": ["bitwarden"],
            },
            headers=_headers(token),
        )
        assert preview.status_code == 200
        payload = preview.json()
        operation = payload["operations"][0]
        assert operation["action"] == "update"
        assert operation["changed_fields"] == ["password", "url", "notes"]
        assert operation["username_display"] == "f***@example.test"
        assert operation["website_host"] == "accounts.example.test"
        rendered = json.dumps(payload)
        for secret in (
            "full.user@example.test",
            "generated-before-update-secret",
            "generated-after-update-secret",
            "generated private note before",
            "generated private note after",
            "private=before",
            "private=after",
        ):
            assert secret not in rendered


def test_connected_service_delete_previews_device_deletion(api_client) -> None:
    client, _ = api_client
    adapter = FakeBitwarden()
    adapter.capabilities = AdapterCapabilities(
        authoritative_list=True,
        revision_token=True,
        idempotent_create=False,
        delete_confirm=True,
        absence_is_delete=True,
    )
    remote = SecretEntry(
        title="Removed remotely",
        username="remote.delete@example.test",
        password="generated-remote-delete-secret",
        url="https://vault.example.test/login",
        source=Source.BITWARDEN,
        external_id="remote-delete",
        remote_updated_at="revision-delete",
    )
    remote.link_source(Source.BITWARDEN, "remote-delete")
    adapter.entries["remote-delete"] = remote
    token = _unlock(client)

    with (
        patch("vault_unified.manager.get_adapter", return_value=adapter),
        patch("vault_unified.sync.engine.get_adapter", return_value=adapter),
    ):
        initial = client.post(
            "/api/sync/preview",
            json={
                "include_pull": True,
                "include_push": False,
                "sources": ["bitwarden"],
            },
            headers=_headers(token),
        )
        pulled = client.post(
            "/api/sync/execute",
            json={"preview_token": initial.json()["preview_token"]},
            headers=_headers(token),
        )
        assert pulled.status_code == 200
        entries = client.get("/api/entries", headers=_headers(token))
        assert entries.status_code == 200
        local_id = entries.json()[0]["id"]
        adapter.entries.clear()

        preview = client.post(
            "/api/sync/preview",
            json={
                "include_pull": True,
                "include_push": False,
                "sources": ["bitwarden"],
            },
            headers=_headers(token),
        )
        assert preview.status_code == 200
        deletion = preview.json()["operations"][0]
        assert deletion["action"] == "delete"
        assert deletion["deletion_side"] == "this_device"
        assert deletion["local_id"] == local_id
        assert deletion["title"] == "Removed remotely"

        execute = client.post(
            "/api/sync/execute",
            json={"preview_token": preview.json()["preview_token"]},
            headers=_headers(token),
        )
        assert execute.status_code == 200
        outcome = execute.json()["operations"][0]
        assert outcome["operation_id"] == deletion["operation_id"]
        assert outcome["status"] == "completed"


def test_executor_never_scans_or_pushes_an_unapproved_dirty_entry(
    tmp_path: Path,
) -> None:
    vault_path = tmp_path / "approved-only.vault"
    local = LocalVault.create(vault_path, "generated-approved-only-password")
    save_prefs(vault_path, SyncPreferences(enabled_sources=["bitwarden"]))
    first = local.add(
        SecretEntry(
            title="Approved entry",
            username="approved@example.test",
            password="generated-approved-secret",
        )
    )
    second = local.add(
        SecretEntry(
            title="Not approved entry",
            username="not-approved@example.test",
            password="generated-not-approved-secret",
        )
    )
    vault = MagicMock()
    vault.local = local
    vault.vault_path = vault_path
    vault._last_errors = []
    engine = MetadataPreservingSyncEngine(vault)
    vault.sync = engine
    adapter = FakeBitwarden()

    with (
        patch("vault_unified.manager.get_adapter", return_value=adapter),
        patch("vault_unified.sync.engine.get_adapter", return_value=adapter),
    ):
        plan = engine.preview_explicit(
            [Source.BITWARDEN],
            include_pull=False,
            include_push=True,
        )
        approved = next(
            operation
            for operation in plan["operations"]
            if operation["local_id"] == first.id
        )
        result = engine.execute_explicit(
            [Source.BITWARDEN],
            include_pull=False,
            include_push=True,
            approved_operations=[approved],
        )

    assert adapter.create_calls == 1
    assert len(adapter.entries) == 1
    assert result.operations[0]["operation_id"] == approved["operation_id"]
    assert result.operations[0]["status"] == "completed"
    assert local.get(second.id).sync_status.value == "dirty"
    assert local.get(second.id).get_linked_id(Source.BITWARDEN) == ""


def test_unavailable_source_operation_is_never_reported_as_success(
    api_client,
) -> None:
    client, _ = api_client
    adapter = FakeBitwarden()
    adapter.available = False
    token = _unlock(client)
    created = client.post(
        "/api/entries",
        json={
            "title": "Unavailable source item",
            "username": "offline@example.test",
            "password": "generated-offline-secret",
        },
        headers=_headers(token),
    )
    assert created.status_code == 200

    with (
        patch("vault_unified.manager.get_adapter", return_value=adapter),
        patch("vault_unified.sync.engine.get_adapter", return_value=adapter),
    ):
        preview = client.post(
            "/api/sync/preview",
            json={
                "include_pull": False,
                "include_push": True,
                "sources": ["bitwarden"],
            },
            headers=_headers(token),
        )
        assert preview.status_code == 200
        assert preview.json()["per_source"]["bitwarden"]["status"] == "unavailable"

        execute = client.post(
            "/api/sync/execute",
            json={"preview_token": preview.json()["preview_token"]},
            headers=_headers(token),
        )
        assert execute.status_code == 200
        outcome = execute.json()["operations"][0]
        assert outcome["status"] == "failed"
        assert outcome["next_step"] == "create_new_preview"
        assert execute.json()["pushed"] == {"pushed": 0, "errors": 1}

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("fastapi")

from vault_unified import integration_credentials as credentials
from vault_unified.api.app import create_app
from vault_unified.manager import UnifiedVault
from vault_unified.session import sessions

BOOTSTRAP_SECRET = "integration-api-secret-0123456789abcdef"


@pytest.fixture
def integration_api(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        vault_file = root / "secrets.vault"
        config_file = root / "config" / "integrations.json"
        secret_store: dict[tuple[str, str], str] = {}
        monkeypatch.setenv("VAULT_FILE", str(vault_file))
        monkeypatch.setattr(credentials, "integration_config_path", lambda: config_file)
        monkeypatch.setattr(
            credentials,
            "_keyring_get",
            lambda source, key: secret_store.get((source, key)),
        )
        monkeypatch.setattr(
            credentials,
            "_keyring_set",
            lambda source, key, value: secret_store.__setitem__((source, key), value),
        )
        monkeypatch.setattr(
            credentials,
            "_keyring_delete",
            lambda source, key: secret_store.pop((source, key), None),
        )
        for spec in credentials.INTEGRATION_SPECS.values():
            for field in spec.fields:
                monkeypatch.delenv(field.key, raising=False)
        UnifiedVault.create(vault_file, "vault-password")
        sessions._sessions.clear()
        app = create_app(
            bootstrap_secret=BOOTSTRAP_SECRET,
            instance_id="integration-api-test",
        )
        with TestClient(app) as client:
            unlock = client.post(
                "/api/auth/unlock",
                json={"password": "vault-password", "remember": False},
                headers={"X-Vault-Bootstrap": BOOTSTRAP_SECRET},
            )
            assert unlock.status_code == 200
            headers = {
                "X-Vault-Bootstrap": BOOTSTRAP_SECRET,
                "Authorization": f"Bearer {unlock.json()['token']}",
            }
            yield client, headers, config_file, secret_store
        sessions._sessions.clear()


def test_integration_api_never_returns_or_serializes_secrets(integration_api) -> None:
    client, headers, config_file, secret_store = integration_api
    client_secret = "NEVER_RETURN_API_CLIENT_SECRET"
    master_password = "NEVER_RETURN_API_MASTER_PASSWORD"

    unauthenticated = client.get(
        "/api/integrations",
        headers={"X-Vault-Bootstrap": BOOTSTRAP_SECRET},
    )
    assert unauthenticated.status_code == 401

    saved = client.put(
        "/api/integrations/bitwarden",
        headers=headers,
        json={
            "values": {
                "BW_CLIENTID": "user.test",
                "BW_CLIENTSECRET": client_secret,
                "BW_PASSWORD": master_password,
            },
            "clear": [],
        },
    )
    assert saved.status_code == 200
    body = saved.json()
    encoded = json.dumps(body)
    assert client_secret not in encoded
    assert master_password not in encoded
    secret_fields = [field for field in body["fields"] if field["secret"]]
    assert all(field["value"] == "" for field in secret_fields)
    assert all(field["present"] for field in secret_fields)

    disk = config_file.read_text(encoding="utf-8")
    assert client_secret not in disk
    assert master_password not in disk
    assert secret_store[("bitwarden", "BW_CLIENTSECRET")] == client_secret
    assert secret_store[("bitwarden", "BW_PASSWORD")] == master_password

    listing = client.get("/api/integrations", headers=headers)
    assert listing.status_code == 200
    assert client_secret not in listing.text
    assert master_password not in listing.text


def test_delete_clears_keyring_and_local_config(integration_api) -> None:
    client, headers, _, secret_store = integration_api
    saved = client.put(
        "/api/integrations/proton_pass",
        headers=headers,
        json={
            "values": {
                "PROTON_PASS_PERSONAL_ACCESS_TOKEN": "temporary-token",
                "PROTON_PASS_VAULT_NAME": "Personal",
            },
            "clear": [],
        },
    )
    assert saved.status_code == 200
    assert secret_store

    cleared = client.delete("/api/integrations/proton_pass", headers=headers)
    assert cleared.status_code == 200
    assert not secret_store
    assert cleared.json()["configured"] is False

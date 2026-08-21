from __future__ import annotations

import json

import pytest

from vault_unified import integration_credentials as credentials


@pytest.fixture
def fake_store(monkeypatch, tmp_path):
    secret_store: dict[tuple[str, str], str] = {}
    config_path = tmp_path / "config" / "integrations.json"
    monkeypatch.setattr(credentials, "integration_config_path", lambda: config_path)
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
    return secret_store, config_path


def test_secrets_use_keyring_and_never_enter_config_or_snapshot(fake_store) -> None:
    secret_store, config_path = fake_store
    client_secret = "NEVER_WRITE_THIS_CLIENT_SECRET"
    master_password = "NEVER_WRITE_THIS_MASTER_PASSWORD"

    credentials.update_source_settings(
        "bitwarden",
        {
            "BW_CLIENTID": "user.example",
            "BW_CLIENTSECRET": client_secret,
            "BW_PASSWORD": master_password,
            "BW_SERVER": "https://vault.example.test",
        },
    )

    raw = config_path.read_text(encoding="utf-8")
    assert client_secret not in raw
    assert master_password not in raw
    parsed = json.loads(raw)
    assert parsed["sources"]["bitwarden"] == {
        "BW_CLIENTID": "user.example",
        "BW_SERVER": "https://vault.example.test",
    }
    assert secret_store[("bitwarden", "BW_CLIENTSECRET")] == client_secret
    assert secret_store[("bitwarden", "BW_PASSWORD")] == master_password

    snapshot = credentials.integration_snapshot("bitwarden")
    assert snapshot["configured"] is True
    secret_fields = [field for field in snapshot["fields"] if field["secret"]]
    assert all(field["value"] == "" for field in secret_fields)
    assert all(field["present"] is True for field in secret_fields)
    assert client_secret not in json.dumps(snapshot)
    assert master_password not in json.dumps(snapshot)

    runtime = credentials.get_source_settings("bitwarden")
    assert runtime["BW_CLIENTSECRET"] == client_secret
    assert runtime["BW_PASSWORD"] == master_password


def test_environment_is_read_only_compatibility_fallback(fake_store, monkeypatch) -> None:
    _, config_path = fake_store
    monkeypatch.setenv("PROTON_PASS_PERSONAL_ACCESS_TOKEN", "environment-token")
    monkeypatch.setenv("PROTON_PASS_VAULT_NAME", "Environment Vault")

    snapshot = credentials.integration_snapshot("proton_pass")
    token = next(
        field
        for field in snapshot["fields"]
        if field["key"] == "PROTON_PASS_PERSONAL_ACCESS_TOKEN"
    )
    name = next(
        field
        for field in snapshot["fields"]
        if field["key"] == "PROTON_PASS_VAULT_NAME"
    )
    assert token["present"] is True
    assert token["value"] == ""
    assert token["origin"] == "environment"
    assert name["value"] == "Environment Vault"
    assert not config_path.exists()


def test_clear_removes_keyring_and_nonsecret_config(fake_store) -> None:
    secret_store, config_path = fake_store
    credentials.update_source_settings(
        "keepassxc",
        {
            "KEEPASSXC_DATABASE": "C:/fake/test.kdbx",
            "KEEPASSXC_PASSWORD": "database-password",
        },
    )
    assert secret_store
    assert config_path.exists()

    credentials.clear_source_settings("keepassxc")

    assert not secret_store
    snapshot = credentials.integration_snapshot("keepassxc")
    assert snapshot["configured"] is False
    assert all(not field["present"] for field in snapshot["fields"])
    parsed = json.loads(config_path.read_text(encoding="utf-8"))
    assert "keepassxc" not in parsed["sources"]


def test_unknown_fields_are_rejected_without_writing(fake_store) -> None:
    _, config_path = fake_store
    with pytest.raises(KeyError, match="Unsupported integration field"):
        credentials.update_source_settings(
            "bitwarden",
            {"UNREVIEWED_SECRET": "must-not-be-written"},
        )
    assert not config_path.exists()

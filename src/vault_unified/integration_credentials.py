from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vault_unified.config import get_config_dir
from vault_unified.storage import atomic_write_bytes, require_clean_storage

KEYRING_SERVICE = "vault-unified.integrations"
CONFIG_VERSION = 1


class CredentialStoreError(RuntimeError):
    """The OS credential store could not complete a requested operation."""


@dataclass(frozen=True)
class IntegrationFieldSpec:
    key: str
    label: str
    secret: bool = False
    required: bool = False
    default: str = ""


@dataclass(frozen=True)
class IntegrationSourceSpec:
    source: str
    label: str
    fields: tuple[IntegrationFieldSpec, ...]

    def field(self, key: str) -> IntegrationFieldSpec:
        for item in self.fields:
            if item.key == key:
                return item
        raise KeyError(f"Unsupported integration field: {self.source}.{key}")


INTEGRATION_SPECS: dict[str, IntegrationSourceSpec] = {
    "bitwarden": IntegrationSourceSpec(
        source="bitwarden",
        label="Bitwarden",
        fields=(
            IntegrationFieldSpec("BW_CLIENTID", "Client ID", required=True),
            IntegrationFieldSpec(
                "BW_CLIENTSECRET", "Client secret", secret=True, required=True
            ),
            IntegrationFieldSpec(
                "BW_PASSWORD", "Master password", secret=True, required=True
            ),
            IntegrationFieldSpec(
                "BW_SERVER", "Server", default="https://vault.bitwarden.com"
            ),
        ),
    ),
    "keepassxc": IntegrationSourceSpec(
        source="keepassxc",
        label="KeePassXC",
        fields=(
            IntegrationFieldSpec(
                "KEEPASSXC_DATABASE", "Database path", required=True
            ),
            IntegrationFieldSpec(
                "KEEPASSXC_PASSWORD",
                "Database master password",
                secret=True,
                required=True,
            ),
            IntegrationFieldSpec("KEEPASSXC_KEY_FILE", "Key file path"),
            IntegrationFieldSpec("KEEPASSXC_GROUP", "Group"),
        ),
    ),
    "gopass": IntegrationSourceSpec(
        source="gopass",
        label="gopass",
        fields=(
            IntegrationFieldSpec("GOPASS_STORE", "Store path"),
            IntegrationFieldSpec("GOPASS_MOUNT", "Mount"),
            IntegrationFieldSpec(
                "GOPASS_PATH_PREFIX", "Path prefix", default="vault"
            ),
        ),
    ),
    "proton_pass": IntegrationSourceSpec(
        source="proton_pass",
        label="Proton Pass",
        fields=(
            IntegrationFieldSpec(
                "PROTON_PASS_PERSONAL_ACCESS_TOKEN",
                "Personal access token",
                secret=True,
                required=True,
            ),
            IntegrationFieldSpec("PROTON_PASS_SHARE_ID", "Share ID"),
            IntegrationFieldSpec(
                "PROTON_PASS_VAULT_NAME", "Vault name", default="Personal"
            ),
        ),
    ),
}


def integration_config_path() -> Path:
    return get_config_dir() / "integrations.json"


def _keyring_account(source: str, key: str) -> str:
    return f"{source}:{key}"


def _keyring_get(source: str, key: str) -> str | None:
    try:
        import keyring

        return keyring.get_password(KEYRING_SERVICE, _keyring_account(source, key))
    except Exception:
        return None


def _keyring_set(source: str, key: str, value: str) -> None:
    try:
        import keyring

        keyring.set_password(KEYRING_SERVICE, _keyring_account(source, key), value)
    except Exception as exc:
        raise CredentialStoreError(
            "The operating-system credential store is unavailable"
        ) from exc


def _keyring_delete(source: str, key: str) -> None:
    try:
        import keyring

        keyring.delete_password(KEYRING_SERVICE, _keyring_account(source, key))
    except Exception as exc:
        try:
            import keyring

            if isinstance(exc, keyring.errors.PasswordDeleteError):
                return
        except Exception:
            pass
        raise CredentialStoreError(
            "The operating-system credential store is unavailable"
        ) from exc


def _validate_config(value: Any) -> dict[str, dict[str, str]]:
    if value in (None, {}):
        return {}
    if not isinstance(value, dict) or value.get("version") != CONFIG_VERSION:
        raise ValueError("Integration configuration has an unsupported schema")
    raw_sources = value.get("sources")
    if not isinstance(raw_sources, dict):
        raise ValueError("Integration configuration sources must be an object")
    result: dict[str, dict[str, str]] = {}
    for source, raw_fields in raw_sources.items():
        spec = INTEGRATION_SPECS.get(source)
        if spec is None or not isinstance(raw_fields, dict):
            raise ValueError("Integration configuration contains an unknown source")
        clean: dict[str, str] = {}
        for key, field_value in raw_fields.items():
            field = spec.field(key)
            if field.secret:
                raise ValueError("Secrets are forbidden in integration configuration")
            if not isinstance(field_value, str):
                raise ValueError("Integration configuration values must be text")
            if field_value:
                clean[key] = field_value
        if clean:
            result[source] = clean
    return result


def load_integration_config() -> dict[str, dict[str, str]]:
    path = integration_config_path()
    require_clean_storage(path)
    if not path.exists():
        return {}
    if path.is_symlink() or not path.is_file():
        raise ValueError("Integration configuration must be a regular file")
    parsed = json.loads(path.read_text(encoding="utf-8"))
    return _validate_config(parsed)


def _save_integration_config(config: dict[str, dict[str, str]]) -> None:
    path = integration_config_path()
    payload = {
        "version": CONFIG_VERSION,
        "sources": {
            source: dict(sorted(fields.items()))
            for source, fields in sorted(config.items())
            if fields
        },
    }
    encoded = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")

    def validate(candidate: bytes) -> None:
        _validate_config(json.loads(candidate.decode("utf-8")))

    atomic_write_bytes(path, encoded, validator=validate)


def _field_value_with_origin(
    source: str,
    field: IntegrationFieldSpec,
    config: dict[str, dict[str, str]],
) -> tuple[str, str]:
    if field.secret:
        stored = _keyring_get(source, field.key)
        if stored is not None:
            return stored, "keyring"
        environment = os.environ.get(field.key, "")
        if environment:
            return environment, "environment"
        return "", ""

    configured = config.get(source, {}).get(field.key)
    if configured is not None:
        return configured, "config"
    environment = os.environ.get(field.key, "")
    if environment:
        return environment, "environment"
    if field.default:
        return field.default, "default"
    return "", ""


def get_source_settings(source: str) -> dict[str, str]:
    spec = INTEGRATION_SPECS.get(source)
    if spec is None:
        raise KeyError(f"Unknown integration source: {source}")
    config = load_integration_config()
    return {
        field.key: _field_value_with_origin(source, field, config)[0]
        for field in spec.fields
    }


def source_environment(source: str) -> dict[str, str]:
    env = os.environ.copy()
    for key, value in get_source_settings(source).items():
        if value:
            env[key] = value
        else:
            env.pop(key, None)
    return env


def integration_snapshot(source: str) -> dict[str, Any]:
    spec = INTEGRATION_SPECS.get(source)
    if spec is None:
        raise KeyError(f"Unknown integration source: {source}")
    config = load_integration_config()
    fields: list[dict[str, Any]] = []
    required_present = True
    for field in spec.fields:
        value, origin = _field_value_with_origin(source, field, config)
        present = bool(value)
        if field.required and not present:
            required_present = False
        fields.append(
            {
                "key": field.key,
                "label": field.label,
                "secret": field.secret,
                "required": field.required,
                "value": "" if field.secret else value,
                "present": present,
                "origin": origin,
            }
        )
    return {
        "source": source,
        "label": spec.label,
        "configured": required_present,
        "fields": fields,
    }


def list_integration_snapshots() -> list[dict[str, Any]]:
    return [integration_snapshot(source) for source in INTEGRATION_SPECS]


def update_source_settings(
    source: str,
    values: dict[str, str],
    clear: list[str] | None = None,
) -> None:
    spec = INTEGRATION_SPECS.get(source)
    if spec is None:
        raise KeyError(f"Unknown integration source: {source}")
    clear_fields = set(clear or [])
    unknown = (set(values) | clear_fields) - {field.key for field in spec.fields}
    if unknown:
        raise KeyError(f"Unsupported integration field: {sorted(unknown)[0]}")

    config = load_integration_config()
    source_config = dict(config.get(source, {}))
    for key in clear_fields:
        field = spec.field(key)
        if field.secret:
            _keyring_delete(source, key)
        else:
            source_config.pop(key, None)

    for key, value in values.items():
        if not isinstance(value, str):
            raise TypeError("Integration values must be text")
        field = spec.field(key)
        if field.secret:
            if value:
                _keyring_set(source, key, value)
            else:
                _keyring_delete(source, key)
        elif value:
            source_config[key] = value
        else:
            source_config.pop(key, None)

    if source_config:
        config[source] = source_config
    else:
        config.pop(source, None)
    _save_integration_config(config)


def clear_source_settings(source: str) -> None:
    spec = INTEGRATION_SPECS.get(source)
    if spec is None:
        raise KeyError(f"Unknown integration source: {source}")
    config = load_integration_config()
    for field in spec.fields:
        if field.secret:
            _keyring_delete(source, field.key)
    config.pop(source, None)
    _save_integration_config(config)

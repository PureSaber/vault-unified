from __future__ import annotations

import subprocess

import pytest

from vault_unified.adapters.base import REDACTED, CliAdapter
from vault_unified.models import SecretEntry, Source


class DummyCliAdapter(CliAdapter):
    name = "Dummy"
    cli_name = "dummy-cli"
    source = Source.LOCAL

    def list_entries(self) -> list[SecretEntry]:
        return []

    def get_entry(self, external_id: str) -> SecretEntry | None:
        return None

    def create_entry(
        self, entry: SecretEntry, *, operation_id: str | None = None
    ) -> SecretEntry:
        return entry

    def update_entry(
        self, entry: SecretEntry, *, operation_id: str | None = None
    ) -> SecretEntry:
        return entry

    def delete_entry(
        self,
        external_id: str,
        *,
        permanent: bool = False,
        operation_id: str | None = None,
    ) -> None:
        return None


def test_timeout_error_never_contains_command_payload(monkeypatch) -> None:
    sentinel = "NEVER_LEAK_THIS_ENCODED_PASSWORD_PAYLOAD_0123456789"

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd=["dummy-cli", "create", "item", sentinel],
            timeout=30,
        )

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(RuntimeError) as exc_info:
        DummyCliAdapter()._run(["create", "item", sentinel])

    message = str(exc_info.value)
    assert sentinel not in message
    assert message == "dummy-cli command timed out after 30s"


def test_failed_command_redacts_environment_input_and_long_arguments(monkeypatch) -> None:
    env_secret = "NEVER_LEAK_THIS_ENV_PASSWORD"
    stdin_secret = '{"password":"NEVER_LEAK_THIS_STDIN_PASSWORD"}'
    encoded_payload = "NEVER_LEAK_THIS_LONG_ARGUMENT_0123456789"
    monkeypatch.setenv("BW_PASSWORD", env_secret)

    def failed(command, **kwargs):
        text = f"{env_secret} {stdin_secret} {encoded_payload}"
        return subprocess.CompletedProcess(command, 1, stdout=text, stderr=text)

    monkeypatch.setattr(subprocess, "run", failed)
    result = DummyCliAdapter()._run(
        ["create", "item", encoded_payload],
        input_text=stdin_secret,
    )

    assert result.returncode == 1
    assert env_secret not in (result.stderr or "")
    assert stdin_secret not in (result.stderr or "")
    assert encoded_payload not in (result.stderr or "")
    assert result.stderr == f"{REDACTED} {REDACTED} {REDACTED}"
    assert result.stdout == f"{REDACTED} {REDACTED} {REDACTED}"

from __future__ import annotations

import os
import re
import shutil
import subprocess
from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping

from vault_unified.models import SecretEntry, Source
from vault_unified.sync.ledger import AdapterCapabilities

CLI_TIMEOUT = 30
REDACTED = "[REDACTED]"
_SENSITIVE_KEY_PARTS = (
    "PASSWORD",
    "PASSWD",
    "SECRET",
    "TOKEN",
    "SESSION",
    "CREDENTIAL",
    "PRIVATE_KEY",
    "API_KEY",
    "PAT",
)


def _looks_sensitive_argument(value: str) -> bool:
    stripped = value.strip()
    if not stripped or stripped.startswith("-"):
        return False
    return (
        len(stripped) >= 32
        or "\n" in stripped
        or "\r" in stripped
        or ("{" in stripped and "}" in stripped)
    )


def _secret_values(
    args: Iterable[str],
    env: Mapping[str, str] | None,
    input_text: str | None,
) -> list[str]:
    values: set[str] = set()
    combined_env = dict(os.environ)
    if env:
        combined_env.update(env)
    for key, value in combined_env.items():
        upper = key.upper()
        if value and any(part in upper for part in _SENSITIVE_KEY_PARTS):
            values.add(value)
    if input_text:
        values.add(input_text)

    previous = ""
    for value in args:
        previous_upper = previous.upper().lstrip("-")
        if value and (
            any(part in previous_upper for part in _SENSITIVE_KEY_PARTS)
            or _looks_sensitive_argument(value)
        ):
            values.add(value)
        previous = value
    return sorted(values, key=len, reverse=True)


def _redact_text(text: str | None, secrets: Iterable[str]) -> str | None:
    if text is None:
        return None
    redacted = text
    for secret in secrets:
        if not secret:
            continue
        if len(secret) >= 4:
            redacted = redacted.replace(secret, REDACTED)
        else:
            redacted = re.sub(
                rf"(?<!\w){re.escape(secret)}(?!\w)",
                REDACTED,
                redacted,
            )
    return redacted


class VaultAdapter(ABC):
    """Base class for external password manager integrations."""

    name: str = "base"
    source: Source = Source.LOCAL
    capabilities = AdapterCapabilities()

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if the external tool can perform operations."""

    @abstractmethod
    def is_configured(self) -> bool:
        """Return True if CLI is installed and credentials are set."""

    @abstractmethod
    def list_entries(self) -> list[SecretEntry]:
        """Fetch all entries from the external vault."""

    @abstractmethod
    def get_entry(self, external_id: str) -> SecretEntry | None:
        """Fetch a single entry by remote ID."""

    @abstractmethod
    def create_entry(
        self, entry: SecretEntry, *, operation_id: str | None = None
    ) -> SecretEntry:
        """Create remote entry; mutates entry with external_id."""

    @abstractmethod
    def update_entry(
        self, entry: SecretEntry, *, operation_id: str | None = None
    ) -> SecretEntry:
        """Update existing remote entry."""

    @abstractmethod
    def delete_entry(
        self,
        external_id: str,
        *,
        permanent: bool = False,
        operation_id: str | None = None,
    ) -> None:
        """Delete remote entry."""

    def status_message(self) -> str:
        if self.is_configured():
            return f"{self.name}: configured"
        if shutil.which(getattr(self, "cli_name", "")):
            return f"{self.name}: CLI found, credentials missing"
        return f"{self.name}: CLI not installed"


class CliAdapter(VaultAdapter):
    cli_name: str = ""

    def _run(
        self,
        args: list[str],
        env: dict[str, str] | None = None,
        *,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        secrets = _secret_values(args, env, input_text)
        try:
            result = subprocess.run(
                [self.cli_name, *args],
                capture_output=True,
                text=True,
                check=False,
                env=env,
                input=input_text,
                timeout=CLI_TIMEOUT,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"{self.cli_name} command timed out after {CLI_TIMEOUT}s"
            ) from exc
        if result.returncode == 0:
            return result
        return subprocess.CompletedProcess(
            args=result.args,
            returncode=result.returncode,
            stdout=_redact_text(result.stdout, secrets),
            stderr=_redact_text(result.stderr, secrets),
        )

    def is_configured(self) -> bool:
        return shutil.which(self.cli_name) is not None

    def is_available(self) -> bool:
        return self.is_configured()

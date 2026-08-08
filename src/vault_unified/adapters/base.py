from __future__ import annotations

import shutil
import subprocess
from abc import ABC, abstractmethod

from vault_unified.models import SecretEntry, Source

CLI_TIMEOUT = 30


class VaultAdapter(ABC):
    """Base class for external password manager integrations."""

    name: str = "base"
    source: Source = Source.LOCAL

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
    def create_entry(self, entry: SecretEntry) -> SecretEntry:
        """Create remote entry; mutates entry with external_id."""

    @abstractmethod
    def update_entry(self, entry: SecretEntry) -> SecretEntry:
        """Update existing remote entry."""

    @abstractmethod
    def delete_entry(self, external_id: str, *, permanent: bool = False) -> None:
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
        try:
            return subprocess.run(
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
                f"{self.cli_name} timed out after {CLI_TIMEOUT}s: {' '.join(args[:3])}"
            ) from exc

    def is_configured(self) -> bool:
        return shutil.which(self.cli_name) is not None

    def is_available(self) -> bool:
        return self.is_configured()

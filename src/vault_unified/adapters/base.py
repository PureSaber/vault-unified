from __future__ import annotations

import shutil
import subprocess
from abc import ABC, abstractmethod

from vault_unified.models import SecretEntry, Source


class VaultAdapter(ABC):
    """Base class for external password manager integrations."""

    name: str = "base"

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if the external tool is installed and configured."""

    @abstractmethod
    def list_entries(self) -> list[SecretEntry]:
        """Fetch all entries from the external vault."""

    def status_message(self) -> str:
        if self.is_configured():
            return f"{self.name}: configured"
        if shutil.which(getattr(self, "cli_name", "")):
            return f"{self.name}: CLI found, credentials missing"
        return f"{self.name}: CLI not installed"

    @abstractmethod
    def is_configured(self) -> bool:
        """Return True if CLI is installed and credentials are set."""


class CliAdapter(VaultAdapter):
    cli_name: str = ""

    def _run(self, args: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [self.cli_name, *args],
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )

    def is_available(self) -> bool:
        return shutil.which(self.cli_name) is not None

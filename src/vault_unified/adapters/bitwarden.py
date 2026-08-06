"""Bitwarden adapter via official `bw` CLI."""

from __future__ import annotations

import json
import os
import subprocess
from typing import Any

from vault_unified.adapters.base import CliAdapter
from vault_unified.models import SecretEntry, Source


class BitwardenAdapter(CliAdapter):
    name = "Bitwarden"
    cli_name = "bw"

    def __init__(self) -> None:
        self._session: str | None = None

    def _ensure_session(self) -> str | None:
        if self._session:
            return self._session
        session = os.environ.get("BW_SESSION")
        if session:
            self._session = session
            return session

        if not os.environ.get("BW_CLIENTID") or not os.environ.get("BW_CLIENTSECRET"):
            return None

        login = self._run(["login", "--apikey", "--raw"])
        if login.returncode != 0 and "already logged in" not in (login.stderr or "").lower():
            return None

        unlock_args = ["unlock", "--raw"]
        if os.environ.get("BW_PASSWORD"):
            unlock_args = ["unlock", "--passwordenv", "BW_PASSWORD", "--raw"]
        unlock = self._run(unlock_args)
        if unlock.returncode != 0:
            return None
        self._session = unlock.stdout.strip()
        return self._session

    def is_configured(self) -> bool:
        if not super().is_available():
            return False
        return bool(
            os.environ.get("BW_CLIENTID")
            and os.environ.get("BW_CLIENTSECRET")
            and os.environ.get("BW_PASSWORD")
        )

    def is_available(self) -> bool:
        if not self.is_configured():
            return False
        return self._ensure_session() is not None

    def _bw(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        session = self._ensure_session()
        if not session:
            raise RuntimeError("Bitwarden session unavailable")
        return self._run([*args, "--session", session])

    def list_entries(self) -> list[SecretEntry]:
        result = self._bw(["list", "items"])
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Failed to list Bitwarden items")
        items: list[dict[str, Any]] = json.loads(result.stdout or "[]")
        entries: list[SecretEntry] = []
        for item in items:
            entry = self._item_to_entry(item)
            if entry:
                entries.append(entry)
        return entries

    def _item_to_entry(self, item: dict[str, Any]) -> SecretEntry | None:
        item_type = item.get("type")
        if item_type not in (1, 2):  # login or secure note
            return None

        login = item.get("login") or {}
        password = login.get("password") or ""
        username = login.get("username") or ""
        url = ""
        if login.get("uris"):
            url = login["uris"][0].get("uri", "")

        notes = item.get("notes") or ""
        if item_type == 2 and not password:
            password = notes

        return SecretEntry(
            title=item.get("name", "Untitled"),
            username=username,
            password=password,
            url=url,
            notes=notes,
            source=Source.BITWARDEN,
            external_id=item.get("id", ""),
        )

"""Proton Pass adapter via official `pass-cli`."""

from __future__ import annotations

import json
import os
from typing import Any

from vault_unified.adapters.base import CliAdapter
from vault_unified.models import SecretEntry, Source


class ProtonPassAdapter(CliAdapter):
    name = "Proton Pass"
    cli_name = "pass-cli"

    def _env(self) -> dict[str, str] | None:
        token = os.environ.get("PROTON_PASS_PERSONAL_ACCESS_TOKEN")
        if not token:
            return None
        env = os.environ.copy()
        env["PROTON_PASS_PERSONAL_ACCESS_TOKEN"] = token
        return env

    def is_configured(self) -> bool:
        return super().is_available() and self._env() is not None

    def is_available(self) -> bool:
        return self.is_configured()

    def list_entries(self) -> list[SecretEntry]:
        env = self._env()
        if not env:
            raise RuntimeError("PROTON_PASS_PERSONAL_ACCESS_TOKEN not set")

        result = self._run(["item", "list", "--output", "json"], env=env)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Failed to list Proton Pass items")

        payload = json.loads(result.stdout or "[]")
        items = payload if isinstance(payload, list) else payload.get("items", [])
        entries: list[SecretEntry] = []
        for item in items:
            entry = self._item_to_entry(item, env)
            if entry:
                entries.append(entry)
        return entries

    def _item_to_entry(self, item: dict[str, Any], env: dict[str, str]) -> SecretEntry | None:
        item_id = item.get("id") or item.get("itemId") or ""
        title = item.get("title") or item.get("name") or "Untitled"

        detail = item
        if item_id:
            view = self._run(["item", "view", item_id, "--output", "json"], env=env)
            if view.returncode == 0 and view.stdout.strip():
                detail = json.loads(view.stdout)

        content = detail.get("content") or detail
        login = content.get("login") or content.get("itemEmail") or {}
        if isinstance(login, str):
            username = login
            password = content.get("password") or content.get("itemPassword") or ""
        else:
            username = login.get("username") or login.get("email") or ""
            password = login.get("password") or ""

        urls = content.get("urls") or content.get("url") or []
        url = ""
        if isinstance(urls, list) and urls:
            first = urls[0]
            url = first.get("url", first) if isinstance(first, dict) else str(first)
        elif isinstance(urls, str):
            url = urls

        notes = content.get("note") or content.get("notes") or detail.get("note") or ""

        return SecretEntry(
            title=title,
            username=username,
            password=password,
            url=url,
            notes=notes,
            source=Source.PROTON_PASS,
            external_id=item_id or title,
        )

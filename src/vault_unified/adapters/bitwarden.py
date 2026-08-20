"""Bitwarden adapter via official `bw` CLI."""

from __future__ import annotations

import json
import os
import subprocess
from typing import Any

from vault_unified.adapters.base import AdapterCapabilities, CliAdapter
from vault_unified.models import SecretEntry, Source


class BitwardenAdapter(CliAdapter):
    capabilities = AdapterCapabilities(
        authoritative_list=True,
        revision_token=True,
        idempotent_create=False,
        delete_confirm=True,
        absence_is_delete=False,
    )
    name = "Bitwarden"
    cli_name = "bw"
    source = Source.BITWARDEN

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
        if not super().is_configured():
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

    def _bw(
        self,
        args: list[str],
        *,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        session = self._ensure_session()
        if not session:
            raise RuntimeError("Bitwarden session unavailable")
        return self._run([*args, "--session", session], input_text=input_text)

    def _encode(self, payload: dict[str, Any]) -> str:
        result = self._run(["encode"], input_text=json.dumps(payload))
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "bw encode failed")
        return result.stdout.strip()

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

    def get_entry(self, external_id: str) -> SecretEntry | None:
        result = self._bw(["get", "item", external_id])
        if result.returncode != 0:
            return None
        item = json.loads(result.stdout)
        return self._item_to_entry(item)

    def create_entry(
        self, entry: SecretEntry, *, operation_id: str | None = None
    ) -> SecretEntry:
        template = self._login_template(entry)
        encoded = self._encode(template)
        result = self._bw(["create", "item", encoded])
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Failed to create Bitwarden item")
        created = json.loads(result.stdout)
        ext_id = created.get("id", "")
        entry.link_source(Source.BITWARDEN, ext_id)
        entry.external_id = ext_id
        entry.remote_updated_at = created.get("revisionDate", "")
        return entry

    def update_entry(
        self, entry: SecretEntry, *, operation_id: str | None = None
    ) -> SecretEntry:
        ext_id = entry.get_linked_id(Source.BITWARDEN) or entry.external_id
        if not ext_id:
            return self.create_entry(entry, operation_id=operation_id)
        result = self._bw(["get", "item", ext_id])
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Failed to get Bitwarden item")
        item = json.loads(result.stdout)
        item["name"] = entry.title
        item.setdefault("login", {})
        item["login"]["username"] = entry.username
        item["login"]["password"] = entry.password
        if entry.url:
            item["login"]["uris"] = [{"uri": entry.url}]
        item["notes"] = entry.notes
        encoded = self._encode(item)
        edit = self._bw(["edit", "item", ext_id, encoded])
        if edit.returncode != 0:
            raise RuntimeError(edit.stderr.strip() or "Failed to update Bitwarden item")
        updated = json.loads(edit.stdout)
        entry.remote_updated_at = updated.get("revisionDate", entry.remote_updated_at)
        return entry

    def delete_entry(
        self,
        external_id: str,
        *,
        permanent: bool = False,
        operation_id: str | None = None,
    ) -> None:
        args = ["delete", "item", external_id]
        if permanent:
            args.append("--permanent")
        result = self._bw(args)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Failed to delete Bitwarden item")

    def _login_template(self, entry: SecretEntry) -> dict[str, Any]:
        result = self._bw(["get", "template", "item"])
        if result.returncode != 0:
            template: dict[str, Any] = {"type": 1, "name": entry.title, "login": {}}
        else:
            template = json.loads(result.stdout)
        template["name"] = entry.title
        template["type"] = 1
        template["login"] = {
            "username": entry.username,
            "password": entry.password,
            "uris": [{"uri": entry.url}] if entry.url else [],
        }
        template["notes"] = entry.notes
        return template

    def _item_to_entry(self, item: dict[str, Any]) -> SecretEntry | None:
        item_type = item.get("type")
        if item_type not in (1, 2):
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

        ext_id = item.get("id", "")
        entry = SecretEntry(
            title=item.get("name", "Untitled"),
            username=username,
            password=password,
            url=url,
            notes=notes,
            source=Source.BITWARDEN,
            external_id=ext_id,
            remote_updated_at=item.get("revisionDate", ""),
        )
        entry.link_source(Source.BITWARDEN, ext_id)
        return entry

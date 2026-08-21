"""Bitwarden adapter via official `bw` CLI."""

from __future__ import annotations

import copy
import json
import os
import subprocess
from typing import Any

from vault_unified.adapters.base import AdapterCapabilities, CliAdapter
from vault_unified.models import SecretEntry, Source

BITWARDEN_LOGIN = 1
BITWARDEN_SECURE_NOTE = 2


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

    @staticmethod
    def _metadata(entry: SecretEntry) -> dict[str, Any]:
        value = entry.source_metadata.get(Source.BITWARDEN.value, {})
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _item_metadata(item: dict[str, Any]) -> dict[str, Any]:
        login = item.get("login") or {}
        secure_note = item.get("secureNote") or {}
        collection_ids = item.get("collectionIds") or []
        return {
            "item_type": item.get("type", BITWARDEN_LOGIN),
            "uris": copy.deepcopy(login.get("uris") or []),
            "fields": copy.deepcopy(item.get("fields") or []),
            "totp": login.get("totp") or "",
            "folder_id": item.get("folderId") or "",
            "favorite": bool(item.get("favorite", False)),
            "reprompt": int(item.get("reprompt") or 0),
            "organization_id": item.get("organizationId") or "",
            "collection_ids": list(collection_ids) if isinstance(collection_ids, list) else [],
            "secure_note_type": int(secure_note.get("type") or 0),
            "has_attachments": bool(item.get("attachments")),
        }

    @staticmethod
    def _updated_uris(metadata: dict[str, Any], url: str) -> list[dict[str, Any]]:
        raw = metadata.get("uris") or []
        uris = copy.deepcopy(raw) if isinstance(raw, list) else []
        if url:
            if uris and isinstance(uris[0], dict):
                uris[0]["uri"] = url
            else:
                uris.insert(0, {"uri": url})
        return uris

    @staticmethod
    def _assert_recreatable(metadata: dict[str, Any]) -> None:
        blockers: list[str] = []
        if metadata.get("has_attachments"):
            blockers.append("attachments")
        if metadata.get("organization_id"):
            blockers.append("organization ownership")
        if metadata.get("collection_ids"):
            blockers.append("collection membership")
        if blockers:
            joined = ", ".join(blockers)
            raise RuntimeError(
                f"Bitwarden item cannot be safely recreated with preserved {joined}"
            )

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
        template = self._create_template(entry)
        encoded = self._encode(template)
        result = self._bw(["create", "item", encoded])
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Failed to create Bitwarden item")
        created = json.loads(result.stdout)
        ext_id = created.get("id", "")
        entry.link_source(Source.BITWARDEN, ext_id)
        entry.external_id = ext_id
        entry.remote_updated_at = created.get("revisionDate", "")
        entry.source_metadata[Source.BITWARDEN.value] = self._item_metadata(created)
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
        item_type = item.get("type")
        if item_type not in (BITWARDEN_LOGIN, BITWARDEN_SECURE_NOTE):
            raise RuntimeError("Unsupported Bitwarden item type; refusing lossy write")

        item["name"] = entry.title
        item["notes"] = entry.notes
        if item_type == BITWARDEN_LOGIN:
            login = item.setdefault("login", {})
            login["username"] = entry.username
            login["password"] = entry.password
            existing_uris = login.get("uris") or []
            metadata = {"uris": existing_uris}
            login["uris"] = self._updated_uris(metadata, entry.url)
        else:
            item.setdefault("secureNote", {"type": 0})

        encoded = self._encode(item)
        edit = self._bw(["edit", "item", ext_id, encoded])
        if edit.returncode != 0:
            raise RuntimeError(edit.stderr.strip() or "Failed to update Bitwarden item")
        updated = json.loads(edit.stdout)
        entry.remote_updated_at = updated.get("revisionDate", entry.remote_updated_at)
        entry.source_metadata[Source.BITWARDEN.value] = self._item_metadata(updated)
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

    def _create_template(self, entry: SecretEntry) -> dict[str, Any]:
        metadata = self._metadata(entry)
        self._assert_recreatable(metadata)
        item_type = metadata.get("item_type", BITWARDEN_LOGIN)
        if item_type not in (BITWARDEN_LOGIN, BITWARDEN_SECURE_NOTE):
            raise RuntimeError("Unsupported Bitwarden item type; refusing lossy write")

        result = self._bw(["get", "template", "item"])
        if result.returncode != 0:
            template: dict[str, Any] = {"type": item_type, "name": entry.title}
        else:
            template = json.loads(result.stdout)
        template["name"] = entry.title
        template["type"] = item_type
        template["notes"] = entry.notes

        if item_type == BITWARDEN_LOGIN:
            login: dict[str, Any] = {
                "username": entry.username,
                "password": entry.password,
                "uris": self._updated_uris(metadata, entry.url),
            }
            if metadata.get("totp"):
                login["totp"] = metadata["totp"]
            template["login"] = login
            template.pop("secureNote", None)
        else:
            template.pop("login", None)
            template["secureNote"] = {
                "type": int(metadata.get("secure_note_type") or 0)
            }

        if metadata.get("fields"):
            template["fields"] = copy.deepcopy(metadata["fields"])
        if metadata.get("folder_id"):
            template["folderId"] = metadata["folder_id"]
        if "favorite" in metadata:
            template["favorite"] = bool(metadata["favorite"])
        if "reprompt" in metadata:
            template["reprompt"] = int(metadata["reprompt"] or 0)
        return template

    def _item_to_entry(self, item: dict[str, Any]) -> SecretEntry | None:
        item_type = item.get("type")
        if item_type not in (BITWARDEN_LOGIN, BITWARDEN_SECURE_NOTE):
            return None

        login = item.get("login") or {}
        username = (login.get("username") or "") if item_type == BITWARDEN_LOGIN else ""
        password = (login.get("password") or "") if item_type == BITWARDEN_LOGIN else ""
        url = ""
        if item_type == BITWARDEN_LOGIN and login.get("uris"):
            first = login["uris"][0]
            if isinstance(first, dict):
                url = first.get("uri", "")

        ext_id = item.get("id", "")
        entry = SecretEntry(
            title=item.get("name", "Untitled"),
            username=username,
            password=password,
            url=url,
            notes=item.get("notes") or "",
            source=Source.BITWARDEN,
            external_id=ext_id,
            remote_updated_at=item.get("revisionDate", ""),
            source_metadata={
                Source.BITWARDEN.value: self._item_metadata(item),
            },
        )
        entry.link_source(Source.BITWARDEN, ext_id)
        return entry

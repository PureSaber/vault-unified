"""Proton Pass adapter via official `pass-cli`."""

from __future__ import annotations

import json
import os
from typing import Any

from vault_unified.adapters.base import AdapterCapabilities, CliAdapter
from vault_unified.integration_credentials import get_source_settings, source_environment
from vault_unified.models import SecretEntry, Source


class ProtonPassAdapter(CliAdapter):
    capabilities = AdapterCapabilities(
        authoritative_list=True,
        revision_token=True,
        idempotent_create=False,
        delete_confirm=False,
        absence_is_delete=False,
    )
    name = "Proton Pass"
    cli_name = "pass-cli"
    source = Source.PROTON_PASS

    @staticmethod
    def _settings() -> dict[str, str]:
        return get_source_settings(Source.PROTON_PASS.value)

    def _default_share_id(self) -> str:
        return self._settings().get("PROTON_PASS_SHARE_ID", "")

    def _default_vault_name(self) -> str:
        return self._settings().get("PROTON_PASS_VAULT_NAME", "")

    def _env(self) -> dict[str, str] | None:
        settings = self._settings()
        if not settings.get("PROTON_PASS_PERSONAL_ACCESS_TOKEN"):
            return None
        return source_environment(Source.PROTON_PASS.value)

    def is_configured(self) -> bool:
        return super().is_configured() and self._env() is not None

    def is_available(self) -> bool:
        return self.is_configured()

    def list_entries(self) -> list[SecretEntry]:
        env = self._env()
        if not env:
            raise RuntimeError("Proton Pass token is not configured")

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

    def get_entry(self, external_id: str) -> SecretEntry | None:
        env = self._env()
        if not env:
            return None
        view = self._run(["item", "view", external_id, "--output", "json"], env=env)
        if view.returncode != 0:
            return None
        detail = json.loads(view.stdout)
        return self._parse_detail(detail, external_id)

    def create_entry(
        self, entry: SecretEntry, *, operation_id: str | None = None
    ) -> SecretEntry:
        env = self._env()
        if not env:
            raise RuntimeError("Proton Pass not configured")
        args = ["item", "create", "login", "--title", entry.title]
        if entry.username:
            args.extend(["--username", entry.username])
        password_file = None
        try:
            if entry.password:
                password_file = self._write_secret_file(entry.password)
                args.extend(["--password-file", password_file])
            if entry.url:
                args.extend(["--url", entry.url])
            share_id = entry.proton_share_id or self._default_share_id()
            vault_name = self._default_vault_name()
            if share_id:
                args.extend(["--share-id", share_id])
            elif vault_name:
                args.extend(["--vault-name", vault_name])
            result = self._run(args, env=env)
            if result.returncode != 0 and entry.password and "password-file" in (
                result.stderr or ""
            ).lower():
                raise RuntimeError(
                    "Installed pass-cli does not support --password-file; upgrade it "
                    "instead of exposing the password in process arguments"
                )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or "Failed to create Proton Pass item")
        finally:
            if password_file:
                self._unlink_secret_file(password_file)
        try:
            created = json.loads(result.stdout)
            ext_id = created.get("id") or created.get("itemId", "")
            share = created.get("shareId") or share_id
        except json.JSONDecodeError:
            ext_id = result.stdout.strip()
            share = share_id
        if ext_id:
            entry.link_source(Source.PROTON_PASS, ext_id)
            entry.external_id = ext_id
        if share:
            entry.proton_share_id = share
        return entry

    def update_entry(
        self, entry: SecretEntry, *, operation_id: str | None = None
    ) -> SecretEntry:
        env = self._env()
        if not env:
            raise RuntimeError("Proton Pass not configured")
        ext_id = entry.get_linked_id(Source.PROTON_PASS) or entry.external_id
        if not ext_id:
            return self.create_entry(entry, operation_id=operation_id)
        args = ["item", "update", "--item-id", ext_id]
        share_id = entry.proton_share_id or self._default_share_id()
        if share_id:
            args.extend(["--share-id", share_id])
        elif self._default_vault_name():
            args.extend(["--vault-name", self._default_vault_name()])
        password_file = None
        try:
            for field, value in [
                ("title", entry.title),
                ("username", entry.username),
                ("url", entry.url),
                ("note", entry.notes),
            ]:
                if value:
                    args.extend(["--field", f"{field}={value}"])
            if entry.password:
                password_file = self._write_secret_file(entry.password)
                args.extend(["--field", f"password=@{password_file}"])
            result = self._run(args, env=env)
            if result.returncode != 0 and entry.password:
                raise RuntimeError(
                    result.stderr.strip()
                    or "Password-file field update failed; refusing plaintext argv fallback"
                )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or "Failed to update Proton Pass item")
        finally:
            if password_file:
                self._unlink_secret_file(password_file)
        return entry

    def delete_entry(
        self,
        external_id: str,
        *,
        permanent: bool = False,
        operation_id: str | None = None,
    ) -> None:
        env = self._env()
        if not env:
            raise RuntimeError("Proton Pass not configured")
        share_id = self._default_share_id()
        if not share_id:
            raise RuntimeError("PROTON_PASS_SHARE_ID required for delete")
        result = self._run(
            ["item", "delete", "--share-id", share_id, "--item-id", external_id],
            env=env,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Failed to delete Proton Pass item")

    @staticmethod
    def _write_secret_file(secret: str) -> str:
        import tempfile

        fd, path = tempfile.mkstemp(prefix="vault-proton-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(secret)
        except Exception:
            os.close(fd)
            raise
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return path

    @staticmethod
    def _unlink_secret_file(path: str) -> None:
        try:
            os.unlink(path)
        except OSError:
            pass

    def _item_to_entry(self, item: dict[str, Any], env: dict[str, str]) -> SecretEntry | None:
        item_id = item.get("id") or item.get("itemId") or ""
        if item_id:
            view = self._run(["item", "view", item_id, "--output", "json"], env=env)
            if view.returncode == 0 and view.stdout.strip():
                return self._parse_detail(json.loads(view.stdout), item_id)
        title = item.get("title") or item.get("name") or "Untitled"
        entry = SecretEntry(
            title=title,
            source=Source.PROTON_PASS,
            external_id=item_id or title,
        )
        entry.link_source(Source.PROTON_PASS, item_id)
        return entry

    def _parse_detail(self, detail: dict[str, Any], item_id: str) -> SecretEntry:
        title = detail.get("title") or detail.get("name") or "Untitled"
        content = detail.get("content") or detail
        login = content.get("login") or {}
        if isinstance(login, str):
            username = login
            password = content.get("password") or ""
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
        share_id = (
            detail.get("shareId")
            or detail.get("share_id")
            or content.get("shareId")
            or self._default_share_id()
        )
        remote_updated = detail.get("modifyTime") or detail.get("updatedAt") or ""

        entry = SecretEntry(
            title=title,
            username=username,
            password=password,
            url=url,
            notes=notes,
            source=Source.PROTON_PASS,
            external_id=item_id,
            remote_updated_at=remote_updated,
            proton_share_id=share_id or "",
        )
        entry.link_source(Source.PROTON_PASS, item_id)
        return entry

"""gopass adapter via official `gopass` CLI."""

from __future__ import annotations

import os
import re

from vault_unified.adapters.base import CliAdapter
from vault_unified.models import SecretEntry, Source


class GopassAdapter(CliAdapter):
    name = "gopass"
    cli_name = "gopass"
    source = Source.GOPASS

    def __init__(self) -> None:
        self._mount = os.environ.get("GOPASS_MOUNT", "").strip("/")
        self._prefix = os.environ.get("GOPASS_PATH_PREFIX", "vault").strip("/")

    def _env(self) -> dict[str, str] | None:
        env = os.environ.copy()
        store = os.environ.get("GOPASS_STORE")
        if store:
            env["GOPASS_STORE"] = store
        return env

    def is_configured(self) -> bool:
        return super().is_configured()

    def is_available(self) -> bool:
        if not self.is_configured():
            return False
        result = self._run(["ls"], env=self._env())
        return result.returncode == 0

    def list_entries(self) -> list[SecretEntry]:
        env = self._env()
        args = ["ls", "--flat"]
        if self._mount:
            args.append(self._mount)
        result = self._run(args, env=env)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Failed to list gopass entries")
        entries: list[SecretEntry] = []
        for line in result.stdout.splitlines():
            path = line.strip()
            if not path:
                continue
            if self._mount and not path.startswith(self._mount):
                continue
            entry = self.get_entry(path)
            if entry:
                entries.append(entry)
        return entries

    def get_entry(self, external_id: str) -> SecretEntry | None:
        env = self._env()
        result = self._run(["show", external_id], env=env)
        if result.returncode != 0:
            return None
        return self._parse_show(external_id, result.stdout)

    def create_entry(self, entry: SecretEntry) -> SecretEntry:
        path = self._entry_path(entry)
        body = self._format_body(entry)
        result = self._run(
            ["insert", "-f", path],
            env=self._env(),
            input_text=body,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Failed to create gopass entry")
        entry.link_source(Source.GOPASS, path)
        entry.external_id = path
        return entry

    def update_entry(self, entry: SecretEntry) -> SecretEntry:
        return self.create_entry(entry)

    def delete_entry(self, external_id: str, *, permanent: bool = False) -> None:
        result = self._run(["rm", external_id], env=self._env())
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Failed to delete gopass entry")

    def _entry_path(self, entry: SecretEntry) -> str:
        linked = entry.get_linked_id(Source.GOPASS)
        if linked:
            return linked
        slug = re.sub(r"[^\w\s-]", "", entry.title).strip().lower().replace(" ", "-")
        slug = slug or "entry"
        parts = [p for p in (self._mount, self._prefix, slug) if p]
        return "/".join(parts)

    def _format_body(self, entry: SecretEntry) -> str:
        lines = [entry.password or ""]
        if entry.username:
            lines.append(f"username: {entry.username}")
        if entry.url:
            lines.append(f"url: {entry.url}")
        if entry.notes:
            lines.append(entry.notes)
        return "\n".join(lines) + "\n"

    def _parse_show(self, path: str, output: str) -> SecretEntry:
        lines = [ln for ln in output.splitlines() if ln.strip()]
        password = lines[0] if lines else ""
        username = ""
        url = ""
        notes_lines: list[str] = []
        for line in lines[1:]:
            lower = line.lower()
            if lower.startswith("username:"):
                username = line.split(":", 1)[1].strip()
            elif lower.startswith("url:"):
                url = line.split(":", 1)[1].strip()
            else:
                notes_lines.append(line)
        title = path.rsplit("/", 1)[-1]
        entry = SecretEntry(
            title=title,
            username=username,
            password=password,
            url=url,
            notes="\n".join(notes_lines),
            source=Source.GOPASS,
            external_id=path,
        )
        entry.link_source(Source.GOPASS, path)
        return entry

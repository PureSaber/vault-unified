"""KeePassXC adapter via official `keepassxc-cli`."""

from __future__ import annotations

import os
import re
from pathlib import Path

from vault_unified.adapters.base import CliAdapter
from vault_unified.models import SecretEntry, Source


class KeePassXCAdapter(CliAdapter):
    name = "KeePassXC"
    cli_name = "keepassxc-cli"
    source = Source.KEEPASSXC

    def __init__(self) -> None:
        self._database = os.environ.get("KEEPASSXC_DATABASE", "")
        self._password = os.environ.get("KEEPASSXC_PASSWORD", "")
        self._key_file = os.environ.get("KEEPASSXC_KEY_FILE", "")
        self._group = os.environ.get("KEEPASSXC_GROUP", "")

    def _db_path(self) -> Path | None:
        if not self._database:
            return None
        path = Path(self._database)
        return path if path.is_file() else None

    def is_configured(self) -> bool:
        if not super().is_configured():
            return False
        return self._db_path() is not None and bool(self._password)

    def is_available(self) -> bool:
        if not self.is_configured():
            return False
        result = self._run_db(["ls"])
        return result.returncode == 0

    def _run_db(
        self,
        args: list[str],
        *,
        entry_password: str | None = None,
    ):
        db = self._db_path()
        if not db:
            raise RuntimeError("KEEPASSXC_DATABASE not set or missing")
        cmd: list[str] = []
        if self._key_file:
            cmd.extend(["--key-file", self._key_file])
        cmd.extend(args)
        stdin = self._password
        if entry_password is not None:
            stdin = f"{self._password}\n{entry_password}"
        return self._run(cmd, input_text=stdin)

    def list_entries(self) -> list[SecretEntry]:
        db = self._db_path()
        assert db is not None
        ls_args = ["ls", "-R", str(db)]
        if self._group:
            ls_args.append(self._group)
        result = self._run_db(ls_args)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Failed to list KeePassXC entries")
        paths = self._parse_ls_paths(result.stdout)
        entries: list[SecretEntry] = []
        for path in paths:
            entry = self.get_entry(path)
            if entry:
                entries.append(entry)
        return entries

    def get_entry(self, external_id: str) -> SecretEntry | None:
        db = self._db_path()
        assert db is not None
        # -s/--show-protected reveals Password; -a alone may return PROTECTED.
        result = self._run_db(["show", "-s", "-a", str(db), external_id])
        if result.returncode != 0:
            return None
        return self._parse_show(external_id, result.stdout)

    def create_entry(self, entry: SecretEntry) -> SecretEntry:
        db = self._db_path()
        assert db is not None
        path = self._entry_path(entry)
        args = ["add", str(db), path, "-u", entry.username or ""]
        if entry.url:
            args.extend(["--url", entry.url])
        if entry.notes:
            args.extend(["--notes", entry.notes])
        args.append("-p")
        result = self._run_db(args, entry_password=entry.password or "")
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Failed to create KeePassXC entry")
        entry.link_source(Source.KEEPASSXC, path)
        entry.external_id = path
        return entry

    def update_entry(self, entry: SecretEntry) -> SecretEntry:
        db = self._db_path()
        assert db is not None
        path = entry.get_linked_id(Source.KEEPASSXC) or entry.external_id
        if not path:
            return self.create_entry(entry)
        args = ["edit", str(db), path, "-u", entry.username or ""]
        if entry.url:
            args.extend(["--url", entry.url])
        if entry.notes:
            args.extend(["--notes", entry.notes])
        args.append("-p")
        result = self._run_db(args, entry_password=entry.password or "")
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Failed to update KeePassXC entry")
        entry.link_source(Source.KEEPASSXC, path)
        entry.external_id = path
        return entry

    def delete_entry(self, external_id: str, *, permanent: bool = False) -> None:
        db = self._db_path()
        assert db is not None
        result = self._run_db(["rm", str(db), external_id])
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Failed to delete KeePassXC entry")

    def _entry_path(self, entry: SecretEntry) -> str:
        linked = entry.get_linked_id(Source.KEEPASSXC)
        if linked:
            return linked
        slug = re.sub(r"[^\w\s-]", "", entry.title).strip().replace(" ", "-")
        slug = slug or "entry"
        if self._group:
            return f"{self._group.rstrip('/')}/{slug}"
        return slug

    def _parse_ls_paths(self, output: str) -> list[str]:
        paths: list[str] = []
        for line in output.splitlines():
            line = line.strip()
            if not line or line.endswith("/"):
                continue
            if line.startswith("├") or line.startswith("└") or line.startswith("│"):
                line = re.sub(r"^[├└│\s─]+", "", line).strip()
            if line and not line.endswith("/"):
                paths.append(line)
        return paths

    def _parse_show(self, path: str, output: str) -> SecretEntry:
        title = path.rsplit("/", 1)[-1]
        username = ""
        password = ""
        url = ""
        notes = ""
        for line in output.splitlines():
            lower = line.lower()
            if lower.startswith("title:"):
                title = line.split(":", 1)[1].strip()
            elif lower.startswith("user:") or lower.startswith("username:"):
                username = line.split(":", 1)[1].strip()
            elif lower.startswith("password:"):
                password = line.split(":", 1)[1].strip()
            elif lower.startswith("url:"):
                url = line.split(":", 1)[1].strip()
            elif lower.startswith("notes:"):
                notes = line.split(":", 1)[1].strip()
        entry = SecretEntry(
            title=title,
            username=username,
            password=password,
            url=url,
            notes=notes,
            source=Source.KEEPASSXC,
            external_id=path,
        )
        entry.link_source(Source.KEEPASSXC, path)
        return entry

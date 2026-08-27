"""KeePassXC adapter via official `keepassxc-cli`."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from vault_unified.adapters.base import AdapterCapabilities, CliAdapter
from vault_unified.integration_credentials import get_source_settings
from vault_unified.models import SecretEntry, Source


class KeePassXCAdapter(CliAdapter):
    capabilities = AdapterCapabilities(
        authoritative_list=True,
        revision_token=False,
        idempotent_create=False,
        delete_confirm=True,
        absence_is_delete=False,
    )
    name = "KeePassXC"
    cli_name = "keepassxc-cli"
    source = Source.KEEPASSXC

    @staticmethod
    def _settings() -> dict[str, str]:
        return get_source_settings(Source.KEEPASSXC.value)

    def _db_path(self) -> Path | None:
        database = self._settings().get("KEEPASSXC_DATABASE", "")
        if not database:
            return None
        path = Path(database)
        return path if path.is_file() else None

    def is_configured(self) -> bool:
        if not super().is_configured():
            return False
        settings = self._settings()
        return self._db_path() is not None and bool(settings.get("KEEPASSXC_PASSWORD"))

    def is_available(self) -> bool:
        if not self.is_configured():
            return False
        try:
            self._list_entry_paths()
        except RuntimeError:
            return False
        return True

    def _run_db(
        self,
        args: list[str],
        *,
        entry_password: str | None = None,
    ):
        db = self._db_path()
        if not db:
            raise RuntimeError("KEEPASSXC_DATABASE not set or missing")
        settings = self._settings()
        key_file = settings.get("KEEPASSXC_KEY_FILE", "")
        cmd: list[str] = []
        if key_file:
            cmd.extend(["--key-file", key_file])
        cmd.extend(args)
        database_password = settings.get("KEEPASSXC_PASSWORD", "")
        stdin = database_password
        if entry_password is not None:
            stdin = f"{database_password}\n{entry_password}"
        return self._run(cmd, input_text=stdin)

    def list_entries(self) -> list[SecretEntry]:
        paths = self._list_entry_paths()
        entries: list[SecretEntry] = []
        for path in paths:
            entry = self._read_entry(path)
            if entry:
                entries.append(entry)
        return entries

    def _list_entry_paths(self) -> list[str]:
        db = self._db_path()
        assert db is not None
        group = self._settings().get("KEEPASSXC_GROUP", "")
        # Flat recursive output preserves the complete group path for every
        # entry.  Tree output only exposes the leaf name, which is ambiguous
        # across groups and cannot round-trip an external ID.
        ls_args = ["ls", "-R", "-f", str(db)]
        if group:
            ls_args.append(group)
        result = self._run_db(ls_args)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Failed to list KeePassXC entries")
        paths = self._parse_ls_paths(result.stdout)
        if group:
            prefix = f"{group.rstrip('/')}/"
            paths = [
                path if path.startswith(prefix) else f"{prefix}{path}"
                for path in paths
            ]
        recycle_bin = self._recycle_bin_group_name()
        if recycle_bin:
            recycle_prefix = f"{recycle_bin.rstrip('/')}/"
            paths = [
                path
                for path in paths
                if path != recycle_bin and not path.startswith(recycle_prefix)
            ]
        return paths

    def _recycle_bin_group_name(self) -> str:
        db = self._db_path()
        assert db is not None
        result = self._run_db(["export", "--format", "xml", str(db)])
        if result.returncode != 0:
            raise RuntimeError(
                result.stderr.strip()
                or "Failed to identify the KeePassXC recycle bin"
            )
        try:
            document = ET.fromstring(result.stdout)
        except ET.ParseError as exc:
            raise RuntimeError("KeePassXC XML export was malformed") from exc
        recycle_uuid = (document.findtext("./Meta/RecycleBinUUID") or "").strip()
        if not recycle_uuid:
            return ""
        for group in document.findall("./Root//Group"):
            if (group.findtext("UUID") or "").strip() == recycle_uuid:
                return (group.findtext("Name") or "").strip()
        return ""

    def get_entry(self, external_id: str) -> SecretEntry | None:
        if external_id not in self._list_entry_paths():
            return None
        return self._read_entry(external_id)

    def _read_entry(self, external_id: str) -> SecretEntry | None:
        db = self._db_path()
        assert db is not None
        # --show-protected reveals Password and --all retains the standard
        # field labels (Title, UserName, Password, URL, Notes).  `-a` takes
        # an attribute name in current KeePassXC releases, so using it without
        # a value shifts the database path into the option and makes reads fail.
        result = self._run_db(["show", "-s", "--all", str(db), external_id])
        if result.returncode != 0:
            return None
        return self._parse_show(external_id, result.stdout)

    def create_entry(
        self, entry: SecretEntry, *, operation_id: str | None = None
    ) -> SecretEntry:
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

    def update_entry(
        self, entry: SecretEntry, *, operation_id: str | None = None
    ) -> SecretEntry:
        db = self._db_path()
        assert db is not None
        path = entry.get_linked_id(Source.KEEPASSXC) or entry.external_id
        if not path:
            return self.create_entry(entry, operation_id=operation_id)
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

    def delete_entry(
        self,
        external_id: str,
        *,
        permanent: bool = False,
        operation_id: str | None = None,
    ) -> None:
        db = self._db_path()
        assert db is not None
        result = self._run_db(["rm", str(db), external_id])
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Failed to delete KeePassXC entry")
        # KeePassXC moves entries to its recycle bin.  `_list_entry_paths`
        # excludes that language-independent recycle-bin group, so follow-up
        # sync reads treat the entry as deleted while preserving recoverability
        # in the native KeePassXC database.

    def _entry_path(self, entry: SecretEntry) -> str:
        linked = entry.get_linked_id(Source.KEEPASSXC)
        if linked:
            return linked
        slug = re.sub(r"[^\w\s-]", "", entry.title).strip().replace(" ", "-")
        slug = slug or "entry"
        group = self._settings().get("KEEPASSXC_GROUP", "")
        if group:
            return f"{group.rstrip('/')}/{slug}"
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

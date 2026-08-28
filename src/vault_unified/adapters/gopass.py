"""gopass adapter via official `gopass` CLI."""

from __future__ import annotations

import re

from vault_unified.adapters.base import AdapterCapabilities, CliAdapter
from vault_unified.integration_credentials import get_source_settings, source_environment
from vault_unified.models import SecretEntry, Source


class GopassAdapter(CliAdapter):
    capabilities = AdapterCapabilities(
        authoritative_list=True,
        revision_token=False,
        idempotent_create=False,
        delete_confirm=True,
        absence_is_delete=False,
    )
    name = "gopass"
    cli_name = "gopass"
    source = Source.GOPASS

    @staticmethod
    def _settings() -> dict[str, str]:
        return get_source_settings(Source.GOPASS.value)

    @staticmethod
    def _env() -> dict[str, str]:
        env = source_environment(Source.GOPASS.value)
        store = GopassAdapter._settings().get("GOPASS_STORE", "").strip()
        if not store:
            return env

        # gopass uses ``mounts.path`` for its active root store.  Its
        # ``PASSWORD_STORE_DIR`` compatibility variable only works while
        # initializing a store, so map Vault Unified's runtime Store path
        # setting through gopass' documented environment configuration API.
        try:
            config_count = max(0, int(env.get("GOPASS_CONFIG_COUNT", "0")))
        except ValueError:
            config_count = 0
        env[f"GOPASS_CONFIG_KEY_{config_count}"] = "mounts.path"
        env[f"GOPASS_CONFIG_VALUE_{config_count}"] = store
        env["GOPASS_CONFIG_COUNT"] = str(config_count + 1)
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
        mount = self._settings().get("GOPASS_MOUNT", "").strip("/")
        args = ["ls", "--flat"]
        if mount:
            args.append(mount)
        result = self._run(args, env=env)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Failed to list gopass entries")
        entries: list[SecretEntry] = []
        for line in result.stdout.splitlines():
            path = line.strip()
            if not path:
                continue
            if mount and not path.startswith(mount):
                continue
            entry = self.get_entry(path)
            if entry:
                entries.append(entry)
        return entries

    def get_entry(self, external_id: str) -> SecretEntry | None:
        result = self._run(["show", external_id], env=self._env())
        if result.returncode != 0:
            return None
        return self._parse_show(external_id, result.stdout)

    def create_entry(
        self, entry: SecretEntry, *, operation_id: str | None = None
    ) -> SecretEntry:
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

    def update_entry(
        self, entry: SecretEntry, *, operation_id: str | None = None
    ) -> SecretEntry:
        return self.create_entry(entry, operation_id=operation_id)

    def delete_entry(
        self,
        external_id: str,
        *,
        permanent: bool = False,
        operation_id: str | None = None,
    ) -> None:
        result = self._run(["rm", "-f", external_id], env=self._env())
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Failed to delete gopass entry")

    def _entry_path(self, entry: SecretEntry) -> str:
        linked = entry.get_linked_id(Source.GOPASS)
        if linked:
            return linked
        settings = self._settings()
        mount = settings.get("GOPASS_MOUNT", "").strip("/")
        prefix = settings.get("GOPASS_PATH_PREFIX", "vault").strip("/")
        slug = re.sub(r"[^\w\s-]", "", entry.title).strip().lower().replace(" ", "-")
        slug = slug or "entry"
        parts = [p for p in (mount, prefix, slug) if p]
        return "/".join(parts)

    def _format_body(self, entry: SecretEntry) -> str:
        lines = [entry.password or ""]
        if entry.title:
            lines.append(f"title: {entry.title}")
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
        title = path.rsplit("/", 1)[-1]
        username = ""
        url = ""
        notes_lines: list[str] = []
        for line in lines[1:]:
            lower = line.lower()
            if lower.startswith("title:"):
                title = line.split(":", 1)[1].strip() or title
            elif lower.startswith("username:"):
                username = line.split(":", 1)[1].strip()
            elif lower.startswith("url:"):
                url = line.split(":", 1)[1].strip()
            else:
                notes_lines.append(line)
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

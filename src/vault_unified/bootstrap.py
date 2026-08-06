from __future__ import annotations

import re
from pathlib import Path

from vault_unified.manager import UnifiedVault
from vault_unified.models import SecretEntry, Source


def import_token_txt(project_root: Path, vault: UnifiedVault) -> int:
    """Import legacy token.txt (e.g. 'github repo : ghp_xxx') into the vault."""
    token_file = project_root / "token.txt"
    if not token_file.exists():
        return 0

    text = token_file.read_text(encoding="utf-8").strip()
    if not text:
        return 0

    title = "GitHub Token"
    username = "repo"
    password = text

    match = re.match(r"^(.+?)\s*:\s*(.+)$", text)
    if match:
        label, value = match.groups()
        title = label.strip().title()
        password = value.strip()
        if "github" in label.lower():
            username = "github"

    existing = vault.get_by_title(title)
    if existing and existing.password == password:
        return 0

    vault.local.upsert(
        SecretEntry(
            title=title,
            username=username,
            password=password,
            notes="Imported from token.txt",
            source=Source.LOCAL,
            tags=["imported", "token.txt"],
        )
    )
    return 1

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

from scripts.build_browser_extension import (
    ARCHIVE_FILES,
    build_extension_archive,
    extension_asset_name,
    verify_extension_archive,
)
from scripts.version_contract import component_versions, require_version_contract


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_all_shipped_components_share_one_release_version() -> None:
    versions = component_versions(REPO_ROOT)
    assert len(set(versions.values())) == 1
    assert require_version_contract(REPO_ROOT) == versions["browser-extension"]


def test_extension_manifest_permissions_are_frozen() -> None:
    manifest = json.loads(
        (REPO_ROOT / "apps/browser-extension/manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["manifest_version"] == 3
    assert manifest["permissions"] == ["activeTab", "scripting", "storage", "tabs"]
    assert manifest["host_permissions"] == [
        "http://127.0.0.1/*",
        "http://localhost/*",
    ]
    assert "content_scripts" not in manifest
    assert "externally_connectable" not in manifest


def test_extension_zip_is_deterministic_allowlisted_and_secret_free(tmp_path: Path) -> None:
    first = build_extension_archive(REPO_ROOT, tmp_path / "first")
    second = build_extension_archive(REPO_ROOT, tmp_path / "second")
    first_bytes = first.read_bytes()
    second_bytes = second.read_bytes()
    assert first.name == extension_asset_name(require_version_contract(REPO_ROOT))
    assert first_bytes == second_bytes
    assert hashlib.sha256(first_bytes).hexdigest() == verify_extension_archive(
        REPO_ROOT,
        first,
    )["sha256"]

    with zipfile.ZipFile(first, "r") as bundle:
        assert tuple(bundle.namelist()) == ARCHIVE_FILES
        assert b"<version>" not in bundle.read("INSTALL.md")
        assert require_version_contract(REPO_ROOT).encode("ascii") in bundle.read("INSTALL.md")
        combined = b"\n".join(bundle.read(name) for name in bundle.namelist())
    assert b"apps/browser-extension" not in combined
    assert b"chrome.storage.session" in combined
    assert b"chrome.storage.local" not in combined
    assert b"chrome.storage.sync" not in combined
    for forbidden in (b".env", b"BEGIN PRIVATE KEY", b"Bearer ", b"bootstrap_secret"):
        assert forbidden not in combined

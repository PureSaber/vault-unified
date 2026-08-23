from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import vault_unified
from vault_unified.api.app import create_app


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_VERSION = "1.1.0"


def test_release_version_is_consistent_across_build_surfaces() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package = json.loads(
        (ROOT / "apps" / "desktop" / "package.json").read_text(encoding="utf-8")
    )
    package_lock = json.loads(
        (ROOT / "apps" / "desktop" / "package-lock.json").read_text(
            encoding="utf-8"
        )
    )
    tauri = json.loads(
        (ROOT / "apps" / "desktop" / "src-tauri" / "tauri.conf.json").read_text(
            encoding="utf-8"
        )
    )
    cargo_toml = tomllib.loads(
        (ROOT / "apps" / "desktop" / "src-tauri" / "Cargo.toml").read_text(
            encoding="utf-8"
        )
    )
    cargo_lock = (ROOT / "apps" / "desktop" / "src-tauri" / "Cargo.lock").read_text(
        encoding="utf-8"
    )
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    release_notes = (ROOT / "docs" / "release-v1.1.0.md").read_text(
        encoding="utf-8"
    )
    root_package = re.search(
        r'\[\[package\]\]\s+name = "vault-unified-desktop"\s+version = "([^"]+)"',
        cargo_lock,
    )

    assert vault_unified.__version__ == EXPECTED_VERSION
    assert create_app().version == EXPECTED_VERSION
    assert pyproject["project"]["version"] == EXPECTED_VERSION
    assert package["version"] == EXPECTED_VERSION
    assert package_lock["version"] == EXPECTED_VERSION
    assert package_lock["packages"][""]["version"] == EXPECTED_VERSION
    assert cargo_toml["package"]["version"] == EXPECTED_VERSION
    assert root_package is not None and root_package.group(1) == EXPECTED_VERSION
    assert tauri["version"] == EXPECTED_VERSION
    assert f"**v{EXPECTED_VERSION}** — 当前版" in readme
    assert release_notes.startswith(f"# Vault Unified v{EXPECTED_VERSION}\n")

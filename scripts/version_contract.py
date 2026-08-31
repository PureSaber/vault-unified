"""Keep every shipped Vault Unified component on one release version."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
TOML_VERSION = re.compile(r'^version\s*=\s*"([^"]+)"\s*(?:#.*)?$')


def _toml_section_version(path: Path, section: str) -> str:
    current = ""
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1].strip()
            continue
        if current == section:
            match = TOML_VERSION.fullmatch(line)
            if match:
                return match.group(1)
    raise ValueError(f"Missing version in [{section}] of {path}")


def component_versions(repo_root: Path) -> dict[str, str]:
    root = repo_root.resolve()
    package = json.loads((root / "apps/desktop/package.json").read_text(encoding="utf-8"))
    tauri = json.loads((root / "apps/desktop/src-tauri/tauri.conf.json").read_text(encoding="utf-8"))
    extension = json.loads((root / "apps/browser-extension/manifest.json").read_text(encoding="utf-8"))
    return {
        "python": _toml_section_version(root / "pyproject.toml", "project"),
        "desktop-package": str(package["version"]),
        "tauri-config": str(tauri["version"]),
        "rust-package": _toml_section_version(root / "apps/desktop/src-tauri/Cargo.toml", "package"),
        "browser-extension": str(extension["version"]),
    }


def require_version_contract(repo_root: Path, expected: str | None = None) -> str:
    versions = component_versions(repo_root)
    unique = set(versions.values())
    if len(unique) != 1:
        details = ", ".join(f"{name}={version}" for name, version in versions.items())
        raise ValueError(f"Release version contract mismatch: {details}")
    version = unique.pop()
    if not SEMVER.fullmatch(version):
        raise ValueError(f"Release version is not x.y.z: {version}")
    if expected is not None and version != expected:
        raise ValueError(f"Release version contract expected {expected}, got {version}")
    return version


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument("--expect", default=None)
    args = parser.parse_args()
    version = require_version_contract(args.repo_root, args.expect)
    print(version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

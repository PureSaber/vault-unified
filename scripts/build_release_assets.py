"""Assemble the version-matched offline kit and optional sharing deployment ZIP."""
from __future__ import annotations

import argparse
import base64
import json
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

try:
    from .build_browser_extension import SECRET_PATTERNS, build_extension_archive
    from .version_contract import require_version_contract
except ImportError:
    from build_browser_extension import SECRET_PATTERNS, build_extension_archive
    from version_contract import require_version_contract


def archive_files(output: Path, files: dict[str, Path]) -> None:
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, path in sorted(files.items()):
            if path.is_symlink() or not path.is_file():
                raise ValueError(f"Missing or unsafe release file: {name}")
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())


def build_assets(root: Path, output: Path) -> dict[str, Path]:
    root, output = root.resolve(), output.resolve()
    version = require_version_contract(root)
    output.mkdir(parents=True, exist_ok=True)
    bundle = root / "apps/desktop/src-tauri/target/release/bundle"
    installers: dict[str, Path] = {}
    platforms = {}
    for kind, pattern in [("nsis", "*-setup.exe"), ("msi", "*.msi")]:
        # Old build output may coexist. Select this version, never an older file.
        found = [p for p in (bundle / kind).glob(pattern) if f"_{version}_" in p.name]
        if len(found) != 1:
            raise ValueError(f"Expected one {kind} installer for {version}")
        installer = found[0]
        signature_path = installer.with_suffix(installer.suffix + ".sig")
        signature = signature_path.read_text(encoding="utf-8").strip()
        comment = base64.b64decode(signature, validate=True).decode("utf-8").splitlines()[2]
        if not comment.startswith("trusted comment: ") or f"version:{version}" not in comment.split("\t"):
            raise ValueError("Installer signature must bind the shipped version")
        # Cryptographic verification is performed by the real updater transport
        # integration test before the build is accepted; this only assembles JSON.
        url_name = quote(installer.name.replace(" ", "."))
        platforms[f"windows-x86_64-{kind}"] = {
            "url": f"https://github.com/PureSaber/vault-unified/releases/download/v{version}/{url_name}",
            "signature": signature,
        }
        installers[installer.name] = installer
        installers[signature_path.name] = signature_path
    platforms["windows-x86_64"] = platforms["windows-x86_64-nsis"]
    notes = root / f"docs/release-v{version}.md"
    latest = output / "latest.json"
    latest.write_text(json.dumps({"version": version, "notes": notes.read_text(encoding="utf-8"),
        "pub_date": datetime.now(timezone.utc).isoformat(), "platforms": platforms}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    extension = build_extension_archive(root, output)
    service = output / f"Vault-Unified-Sharing-Service-v{version}.zip"
    files = {name: root / name for name in ["pyproject.toml", "README.md", "LICENSE", ".dockerignore",
        "deploy/sharing/Dockerfile", "deploy/sharing/compose.yaml", "docs/encrypted-sharing.md"]}
    tracked = subprocess.check_output(["git", "ls-files", "-z", "--", "src/vault_unified"], cwd=root).decode("utf-8").split("\0")
    for name in filter(None, tracked):
        path = root / name
        if path.suffix not in {".py", ".js", ".css", ".html", ".txt", ".md"}:
            raise ValueError(f"Unexpected sharing source file: {name}")
        files[name] = path
    for name, path in files.items():
        if any(pattern.search(path.read_bytes()) for pattern in SECRET_PATTERNS):
            raise ValueError(f"Secret-like content in sharing package source: {name}")
    archive_files(service, files)
    kit = output / f"Vault-Unified-Personal-v{version}-Windows-x64.zip"
    kit_files = {**installers, extension.name: extension, service.name: service, "latest.json": latest,
        "START-HERE.md": root / "docs/personal-edition-start.md", "ACCEPTANCE.md": root / "docs/personal-edition-acceptance.md",
        "RELEASE-NOTES.md": notes}
    archive_files(kit, kit_files)
    return {"kit": kit, "service": service, "extension": extension, "update": latest}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    for label, path in build_assets(args.repo_root, args.output_dir or args.repo_root).items():
        print(f"{label}: {path.name}")

"""Build and verify the deterministic browser-extension release asset."""

from __future__ import annotations

import argparse
import hashlib
import re
import zipfile
from pathlib import Path, PurePosixPath

try:
    from .version_contract import require_version_contract
except ImportError:
    from version_contract import require_version_contract


ARCHIVE_FILES = (
    "INSTALL.md",
    "fill.js",
    "manifest.json",
    "popup.css",
    "popup.html",
    "popup.js",
)
FIXED_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
SECRET_PATTERNS = (
    re.compile(rb"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(rb"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(rb"AKIA[0-9A-Z]{16}"),
    re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)


def extension_asset_name(version: str) -> str:
    return f"Vault-Unified-Browser-Extension-v{version}.zip"


def _safe_member(name: str) -> bool:
    path = PurePosixPath(name)
    return (
        not path.is_absolute()
        and ".." not in path.parts
        and "\\" not in name
        and name in ARCHIVE_FILES
    )


def _validate_content(name: str, data: bytes) -> None:
    if not data:
        raise ValueError(f"Extension release file is empty: {name}")
    if name.lower().endswith((".env", ".log", ".pem", ".key", ".vault")):
        raise ValueError(f"Forbidden extension release file: {name}")
    for pattern in SECRET_PATTERNS:
        if pattern.search(data):
            raise ValueError(f"Secret-like content detected in extension release file: {name}")


def build_extension_archive(repo_root: Path, output_dir: Path | None = None) -> Path:
    root = repo_root.resolve()
    version = require_version_contract(root)
    source = root / "apps/browser-extension"
    destination = (output_dir or root).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / extension_asset_name(version)
    payloads: list[tuple[str, bytes]] = []
    for name in ARCHIVE_FILES:
        path = source / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Required extension release file is missing or unsafe: {name}")
        data = path.read_bytes()
        if name == "INSTALL.md":
            data = data.replace(b"<version>", version.encode("ascii"))
        _validate_content(name, data)
        payloads.append((name, data))

    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as bundle:
        bundle.comment = b""
        for name, data in payloads:
            info = zipfile.ZipInfo(name, date_time=FIXED_TIMESTAMP)
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.extra = b""
            info.comment = b""
            bundle.writestr(info, data)
    verify_extension_archive(root, archive, expected_version=version)
    return archive


def verify_extension_archive(
    repo_root: Path,
    archive: Path,
    *,
    expected_version: str | None = None,
) -> dict[str, object]:
    root = repo_root.resolve()
    version = require_version_contract(root, expected_version)
    path = archive.resolve()
    if path.name != extension_asset_name(version) or path.is_symlink() or not path.is_file():
        raise ValueError("Extension archive name or file type is invalid")
    with zipfile.ZipFile(path, "r") as bundle:
        infos = bundle.infolist()
        names = tuple(info.filename for info in infos)
        if names != ARCHIVE_FILES or len(set(names)) != len(names):
            raise ValueError("Extension archive does not match the release allowlist")
        for info in infos:
            if not _safe_member(info.filename) or info.is_dir():
                raise ValueError(f"Unsafe extension archive member: {info.filename}")
            if info.date_time != FIXED_TIMESTAMP or info.extra or info.comment:
                raise ValueError(f"Extension archive member is not deterministic: {info.filename}")
            _validate_content(info.filename, bundle.read(info))
    data = path.read_bytes()
    return {
        "name": path.name,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "version": version,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--verify", type=Path, default=None)
    parser.add_argument("--expect-version", default=None)
    args = parser.parse_args()
    if args.verify is not None:
        result = verify_extension_archive(
            args.repo_root,
            args.verify,
            expected_version=args.expect_version,
        )
        print(f"Verified {result['name']} {result['bytes']} bytes {result['sha256']}")
    else:
        path = build_extension_archive(args.repo_root, args.output_dir)
        result = verify_extension_archive(args.repo_root, path)
        print(f"Built {path} {result['bytes']} bytes {result['sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

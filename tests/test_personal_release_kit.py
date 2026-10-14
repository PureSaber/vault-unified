import base64
import json
import zipfile
from pathlib import Path

import pytest

from scripts import build_release_assets as release


@pytest.fixture
def source(tmp_path, monkeypatch):
    root = tmp_path / "source"; root.mkdir()
    monkeypatch.setattr(release, "require_version_contract", lambda _: "1.4.0")
    for name in ["pyproject.toml", "README.md", "LICENSE", ".dockerignore", "deploy/sharing/Dockerfile",
                 "deploy/sharing/compose.yaml", "docs/encrypted-sharing.md", "docs/release-v1.4.0.md",
                 "docs/personal-edition-start.md", "docs/personal-edition-acceptance.md", "src/vault_unified/sharing/web/viewer.js"]:
        path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text("generated source")
    monkeypatch.setattr(release.subprocess, "check_output", lambda *a, **k: b"src/vault_unified/sharing/web/viewer.js\0")
    (root / "src/vault_unified/ignored-local.py").write_text("must not ship")
    def extension(_root, output):
        target = output / "Vault-Unified-Browser-Extension-v1.4.0.zip"; target.write_bytes(b"generated extension fixture"); return target
    monkeypatch.setattr(release, "build_extension_archive", extension)
    for kind, ending in [("nsis", "-setup.exe"), ("msi", ".msi")]:
        folder = root / "apps/desktop/src-tauri/target/release/bundle" / kind; folder.mkdir(parents=True)
        for version in ["1.3.0", "1.4.0"]:
            path = folder / f"Vault Unified_{version}_x64{ending}"; path.write_bytes(b"generated nonexecutable installer")
            # Packaging structure fixture, deliberately not a cryptographic signature.
            path.with_suffix(path.suffix + ".sig").write_text(base64.b64encode(f"untrusted comment: fixture\nfixture\ntrusted comment: timestamp:1\tversion:{version}\nfixture".encode()).decode())
    return root


def test_release_kit_matches_versions_and_excludes_untracked_files(source, tmp_path):
    outputs = release.build_assets(source, tmp_path / "output")
    manifest = json.loads(outputs["update"].read_text(encoding="utf-8"))
    assert manifest["version"] == "1.4.0"
    for kind in ["nsis", "msi"]:
        record = manifest["platforms"][f"windows-x86_64-{kind}"]
        assert record["url"].startswith("https://github.com/PureSaber/vault-unified/releases/download/v1.4.0/Vault.Unified_")
        assert "version:1.4.0" in base64.b64decode(record["signature"]).decode()
    with zipfile.ZipFile(outputs["kit"]) as archive:
        assert {"START-HERE.md", "ACCEPTANCE.md", "latest.json", outputs["service"].name, outputs["extension"].name} <= set(archive.namelist())
        assert not any("1.3.0" in name for name in archive.namelist())
    with zipfile.ZipFile(outputs["service"]) as archive:
        assert "src/vault_unified/sharing/web/viewer.js" in archive.namelist()
        assert "src/vault_unified/ignored-local.py" not in archive.namelist()


def test_missing_or_wrong_version_signature_stops_release_assembly(source, tmp_path):
    signature = next((source / "apps/desktop/src-tauri/target/release/bundle/nsis").glob("*1.4.0*.sig"))
    signature.write_text(base64.b64encode(b"untrusted comment: fixture\nfixture\ntrusted comment: timestamp:1\tversion:1.3.0\nfixture").decode())
    with pytest.raises(ValueError, match="bind the shipped version"):
        release.build_assets(source, tmp_path / "bad-version")
    signature.unlink()
    with pytest.raises(FileNotFoundError):
        release.build_assets(source, tmp_path / "missing-signature")

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.scan_repository_secrets import repository_paths, scan_paths


def test_repository_secret_scan_passes_current_tracked_and_untracked_files() -> None:
    assert scan_paths(REPO_ROOT, repository_paths(REPO_ROOT)) == []


def test_secret_scan_detects_provider_token_without_echoing_value(tmp_path: Path) -> None:
    token = b"gh" + b"p_" + (b"A" * 40)
    sample = tmp_path / "sample.txt"
    sample.write_bytes(b"credential=" + token)

    findings = scan_paths(tmp_path, [Path("sample.txt")])

    assert [(item.path, item.line, item.kind) for item in findings] == [
        ("sample.txt", 1, "github-token")
    ]
    assert token.decode("ascii") not in repr(findings)


def test_secret_scan_rejects_private_key_and_secret_file_paths(tmp_path: Path) -> None:
    header = b"-----BEGIN " + b"PRIVATE KEY-----"
    (tmp_path / "identity.txt").write_bytes(header + b"\nnot-a-key\n")
    (tmp_path / ".env").write_text("generated test data", encoding="utf-8")

    findings = scan_paths(tmp_path, [Path("identity.txt"), Path(".env")])

    assert {item.kind for item in findings} == {"private-key", "forbidden-secret-file"}


def test_secret_scan_allows_documented_generated_placeholders(tmp_path: Path) -> None:
    sample = tmp_path / ".env.example"
    sample.write_text(
        "Authorization: Bearer generated-test-only-placeholder\n"
        "TOKEN=<replace-me>\n",
        encoding="utf-8",
    )

    assert scan_paths(tmp_path, [Path(".env.example")]) == []

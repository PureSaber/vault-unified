"""Fail closed on high-confidence secrets or secret-bearing tracked files.

The scanner reports only a path, line number, and detector name. It never echoes
the matching bytes. It scans tracked files plus non-ignored untracked files so it
is useful both before a commit and in CI.
"""

from __future__ import annotations

import argparse
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


MAX_FILE_BYTES = 10 * 1024 * 1024

FORBIDDEN_NAMES = {
    ".env",
    "token.txt",
}
FORBIDDEN_SUFFIXES = {
    ".db",
    ".key",
    ".log",
    ".pem",
    ".vault",
}

SECRET_PATTERNS: tuple[tuple[str, re.Pattern[bytes]], ...] = (
    (
        "private-key",
        re.compile(rb"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"),
    ),
    (
        "github-token",
        re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9]{36,255}|github_pat_[A-Za-z0-9_]{60,255})\b"),
    ),
    ("gitlab-token", re.compile(rb"\bglpat-[A-Za-z0-9_-]{20,}\b")),
    ("aws-access-key", re.compile(rb"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("google-api-key", re.compile(rb"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("slack-token", re.compile(rb"\bxox[baprs]-[0-9A-Za-z-]{20,}\b")),
    ("stripe-live-key", re.compile(rb"\bsk_live_[0-9A-Za-z]{20,}\b")),
    ("npm-token", re.compile(rb"\bnpm_[0-9A-Za-z]{30,}\b")),
    (
        "pypi-token",
        re.compile(rb"\bpypi-AgEIcHlwaS5vcmc[A-Za-z0-9_-]{20,}\b"),
    ),
    (
        "literal-bearer-token",
        re.compile(
            rb"(?i)\bauthorization\s*[:=]\s*['\"]?bearer\s+"
            rb"(?!generated-|example-|fake-|dummy-|redacted|placeholder|<|\$\{)"
            rb"[A-Za-z0-9._~+/-]{20,}"
        ),
    ),
)


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    kind: str


def _is_forbidden_path(relative: Path) -> bool:
    name = relative.name.lower()
    if name in FORBIDDEN_NAMES:
        return True
    if name.startswith(".env.") and name != ".env.example":
        return True
    return relative.suffix.lower() in FORBIDDEN_SUFFIXES


def repository_paths(repo_root: Path) -> list[Path]:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
        ],
        check=True,
        capture_output=True,
    )
    paths: list[Path] = []
    for raw in result.stdout.split(b"\0"):
        if not raw:
            continue
        paths.append(Path(raw.decode("utf-8", errors="strict")))
    return paths


def scan_paths(repo_root: Path, relative_paths: Iterable[Path]) -> list[Finding]:
    root = repo_root.resolve()
    findings: list[Finding] = []
    for supplied in relative_paths:
        relative = Path(supplied)
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            findings.append(Finding(relative.as_posix(), 0, "path-outside-repository"))
            continue
        if not candidate.is_file():
            continue
        display = relative.as_posix()
        if _is_forbidden_path(relative):
            findings.append(Finding(display, 0, "forbidden-secret-file"))
            continue
        size = candidate.stat().st_size
        if size > MAX_FILE_BYTES:
            findings.append(Finding(display, 0, "file-too-large-to-scan"))
            continue
        data = candidate.read_bytes()
        for kind, pattern in SECRET_PATTERNS:
            for match in pattern.finditer(data):
                line = data.count(b"\n", 0, match.start()) + 1
                findings.append(Finding(display, line, kind))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    root = args.repo_root.resolve()
    findings = scan_paths(root, repository_paths(root))
    if findings:
        print("Repository secret scan failed. Matching values are intentionally hidden:")
        for finding in findings:
            location = finding.path if finding.line <= 0 else f"{finding.path}:{finding.line}"
            print(f"- {location}: {finding.kind}")
        return 1
    print("Repository secret scan passed; no high-confidence secret or forbidden secret file found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

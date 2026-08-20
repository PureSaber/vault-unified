from __future__ import annotations

from collections import Counter
from fnmatch import fnmatchcase
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def _block(lines: list[str], key: str, indent: int) -> list[str]:
    prefix = " " * indent + f"{key}:"
    start = next(index for index, line in enumerate(lines) if line == prefix)
    result: list[str] = []
    for line in lines[start + 1 :]:
        if line and len(line) - len(line.lstrip()) <= indent:
            break
        result.append(line)
    return result


def _values(lines: list[str], key: str, indent: int) -> list[str]:
    prefix = " " * indent + f"{key}:"
    index = next(i for i, line in enumerate(lines) if line.startswith(prefix))
    inline = lines[index][len(prefix) :].strip()
    if inline:
        assert inline.startswith("[") and inline.endswith("]")
        return [item.strip().strip("'\"") for item in inline[1:-1].split(",")]

    values: list[str] = []
    for line in lines[index + 1 :]:
        current_indent = len(line) - len(line.lstrip()) if line else indent + 2
        if line and current_indent <= indent:
            break
        match = re.match(r"^\s*-\s*['\"]?([^'\"]+)['\"]?\s*$", line)
        if match:
            values.append(match.group(1))
    return values


def _workflow_starts(event: str, ref: str, branches: list[str], tags: list[str]) -> bool:
    if event in {"pull_request", "workflow_dispatch"}:
        return True
    if event != "push":
        return False
    if ref.startswith("refs/heads/"):
        name = ref.removeprefix("refs/heads/")
        return any(fnmatchcase(name, pattern) for pattern in branches)
    if ref.startswith("refs/tags/"):
        name = ref.removeprefix("refs/tags/")
        return any(fnmatchcase(name, pattern) for pattern in tags)
    return False


def _release_job_runs(ref: str) -> bool:
    return ref.startswith("refs/tags/v")


def test_ci_trigger_and_release_job_contract():
    """Model the documented GitHub branch/tag filters and release job guard."""
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    triggers = _block(lines, "on", 0)
    push = _block(triggers, "push", 2)
    branches = _values(push, "branches", 4)
    tags = _values(push, "tags", 4)

    assert branches == ["main"]
    assert tags == ["v*"]
    assert "  pull_request:" in triggers
    assert "  workflow_dispatch:" in triggers

    release = _block(lines, "release-desktop", 2)
    assert "    if: startsWith(github.ref, 'refs/tags/v')" in release
    assert "    needs: [python, desktop, rustsec]" in release

    cases = [
        ("push", "refs/heads/main", True, False),
        ("push", "refs/heads/feature", False, False),
        ("pull_request", "refs/pull/17/merge", True, False),
        ("workflow_dispatch", "refs/heads/main", True, False),
        ("workflow_dispatch", "refs/tags/v1.0.5", True, True),
        ("push", "refs/tags/v1.0.5", True, True),
        ("push", "refs/tags/test-1.0.5", False, False),
    ]
    for event, ref, starts, releases in cases:
        assert _workflow_starts(event, ref, branches, tags) is starts
        assert (starts and _release_job_runs(ref)) is releases


def test_ci_action_and_permission_contract():
    """Keep action code immutable and write permission scoped to releases."""
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    uses = [
        match.group(1)
        for line in lines
        if (match := re.match(r"^\s*(?:-\s+)?uses:\s+([^\s#]+)", line))
    ]
    expected = Counter(
        {
            "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1": 4,
            "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97": 2,
            "actions/setup-node@820762786026740c76f36085b0efc47a31fe5020": 2,
            "dtolnay/rust-toolchain@4360b52568e2003a75bf9bc1d59f33a8e3fc893c": 2,
            "softprops/action-gh-release@3d0d9888cb7fd7b750713d6e236d1fcb99157228": 1,
        }
    )
    assert Counter(uses) == expected
    assert all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", action) for action in uses)

    workflow_permissions = _block(lines, "permissions", 0)
    assert workflow_permissions == ["  contents: read", ""]

    release = _block(lines, "release-desktop", 2)
    release_permissions = _block(release, "permissions", 4)
    assert release_permissions == ["      contents: write"]
    assert sum("persist-credentials: false" in line for line in lines) == 4

    rustsec = _block(lines, "rustsec", 2)
    assert any("cargo-audit/v0.22.2/" in line for line in rustsec)
    assert any(
        "0a7316540862c13d954f648917ceacca593747baed6eec180fafa590be2710ab"
        in line
        for line in rustsec
    )
    assert any("RustSec/advisory-db.git" in line for line in rustsec)
    assert not any("--ignore" in line for line in rustsec)

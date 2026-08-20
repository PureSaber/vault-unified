from __future__ import annotations

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
    assert "    needs: [python, desktop]" in release

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

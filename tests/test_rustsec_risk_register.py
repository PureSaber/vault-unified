from __future__ import annotations

from datetime import date
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def test_rustsec_register_keeps_active_reviews_and_unfiltered_ci_audit():
    text = (ROOT / "docs" / "rustsec-risk-register.md").read_text(encoding="utf-8")
    assert set(re.findall(r"RUSTSEC-\d{4}-\d{4}", text)) == {
        "RUSTSEC-2024-0370", "RUSTSEC-2024-0429",
        "RUSTSEC-2026-0370", "RUSTSEC-2026-0371", "RUSTSEC-2026-0372",
    }
    deadlines = [date.fromisoformat(value) for value in re.findall(r"review by (\d{4}-\d{2}-\d{2})", text)]
    assert deadlines and all(date.today() <= deadline for deadline in deadlines)
    # CI audits the actual proposed lockfile. Requiring a second, hand-maintained
    # hash in prose only detects ordinary dependency changes, not vulnerabilities.
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    audit_job = workflow.split("  rustsec:\n", 1)[1].split("  release-desktop:\n", 1)[0]
    assert "audit --url https://github.com/RustSec/advisory-db.git --file apps/desktop/src-tauri/Cargo.lock" in audit_job
    assert "--ignore" not in audit_job
    assert "continue-on-error" not in audit_job

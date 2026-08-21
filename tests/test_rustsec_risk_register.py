from __future__ import annotations

from datetime import date
from hashlib import sha256
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
REGISTER = ROOT / "docs" / "rustsec-risk-register.md"
LOCKFILE = ROOT / "apps" / "desktop" / "src-tauri" / "Cargo.lock"

EXPECTED_ADVISORIES = {
    "RUSTSEC-2024-0370",
    "RUSTSEC-2024-0411",
    "RUSTSEC-2024-0412",
    "RUSTSEC-2024-0413",
    "RUSTSEC-2024-0414",
    "RUSTSEC-2024-0415",
    "RUSTSEC-2024-0416",
    "RUSTSEC-2024-0417",
    "RUSTSEC-2024-0418",
    "RUSTSEC-2024-0419",
    "RUSTSEC-2024-0420",
    "RUSTSEC-2024-0429",
    "RUSTSEC-2025-0075",
    "RUSTSEC-2025-0080",
    "RUSTSEC-2025-0081",
    "RUSTSEC-2025-0098",
    "RUSTSEC-2025-0100",
}


def test_rustsec_risk_register_is_complete_and_current():
    text = REGISTER.read_text(encoding="utf-8")
    assert set(re.findall(r"RUSTSEC-\d{4}-\d{4}", text)) == EXPECTED_ADVISORIES
    assert text.count("| **Yes** |") == 5
    assert text.count("| No |") == 12

    deadlines = {
        date.fromisoformat(value)
        for value in re.findall(r"review by (\d{4}-\d{2}-\d{2})", text)
    }
    assert deadlines == {date(2026, 10, 20), date(2026, 11, 20)}
    assert all(date.today() <= deadline for deadline in deadlines)

    # Keep the recorded digest stable across Git checkouts with different
    # core.autocrlf settings while still hashing the full lockfile contents.
    lock_digest = sha256(LOCKFILE.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    assert f"SHA-256 `{lock_digest}`" in text

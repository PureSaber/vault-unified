from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DESIGN = ROOT / "docs" / "vault-v3-threat-model.md"


def _design_text() -> str:
    return DESIGN.read_text(encoding="utf-8")


def test_design_preserves_legacy_and_forbids_automatic_migration() -> None:
    text = _design_text()
    required = (
        "Opening, inspecting, or dry-running a legacy vault MUST NOT write it",
        "MUST NOT silently migrate to v3",
        "MUST NOT fall back to the legacy parser",
        "immutable, byte-for-byte",
        "legacy backup and a recovery receipt",
        "There is no automatic migration at startup, unlock, edit, sync, or release installation",
        "No release may auto-run migration",
    )
    for statement in required:
        assert statement in text


def test_design_covers_crypto_storage_keyring_and_sync_boundaries() -> None:
    text = _design_text()
    required = (
        "Argon2id version 19",
        "`m=65536 KiB`, `t=3`, and `p=4`",
        "KEK wraps only the DEK",
        "fresh payload nonce",
        "ReplaceFileW",
        "decrypt-and-schema validation",
        "MUST NOT add or update raw password entries",
        "same unlocked OS user",
        "Remote absence is not automatically deletion",
        "durable saga",
    )
    for statement in required:
        assert statement in text


def test_design_keeps_implementation_prs_ordered_and_independent() -> None:
    text = _design_text()
    labels = (
        "**5a atomic storage and crash recovery**",
        "**5b format parser/read-only compatibility framework**",
        "**5c Argon2id + KEK/DEK v3**",
        "**5d explicit migration, backup, dry-run, activation, and rollback**",
        "**5e keyring boundary**",
        "**5f sync/conflict/deletion model**",
    )
    positions = [text.index(label) for label in labels]
    assert positions == sorted(positions)
    assert "six independently reviewed and merged PRs, in order" in text


def test_design_requires_fake_fixtures_and_failure_testing() -> None:
    text = _design_text()
    required = (
        "only generated fake vault fixtures",
        "dry-run zero writes",
        "fault injection before and after every write",
        "v3-magic downgrade without legacy fallback",
        "multi-source concurrent edit/delete",
        "no password, entry secret, KEK, DEK, keyring secret",
        "real-vault operation",
        "requiring explicit owner authorization",
    )
    for statement in required:
        assert statement in text

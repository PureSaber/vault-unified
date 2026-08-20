from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from vault_unified.cli import main
from vault_unified.crypto import decrypt_payload, encrypt_payload, write_encrypted_file
from vault_unified.migration import (
    MigrationError,
    MigrationSpaceError,
    apply_v3_migration,
    discover_migration_receipts,
    inspect_v3_migration,
    inspect_migration_receipt_recovery,
    load_migration_receipt,
    plan_v3_migration,
    resume_v3_migration,
    recover_migration_receipt,
    rollback_v3_migration,
)
from vault_unified.storage import atomic_write_bytes, list_backups
from vault_unified.v3_crypto import create_v3_file, decrypt_v3_payload
from vault_unified.vault_format import V3Container, parse_vault_container


LEGACY_PASSWORD = "generated fake legacy password"
V3_PASSWORD = "generated fake v3 password"
FAKE_SECRET = "fixture-only-not-a-real-secret"
FAKE_PAYLOAD = {
    "version": 2,
    "entries": {
        "fake-id": {
            "id": "fake-id",
            "title": "Synthetic migration entry",
            "username": "nobody@example.invalid",
            "password": FAKE_SECRET,
            "url": "https://example.invalid",
            "notes": "generated fixture only",
            "source": "local",
            "external_id": "",
            "tags": ["fake"],
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
            "sync_status": "clean",
            "last_synced_at": "",
            "remote_updated_at": "",
            "proton_share_id": "",
            "linked_sources": {},
        }
    },
}


def _legacy(path: Path, payload: dict | None = None) -> bytes:
    value = payload or FAKE_PAYLOAD
    write_encrypted_file(path, LEGACY_PASSWORD, value)
    return path.read_bytes()


def _receipt(path: Path) -> Path:
    receipts = list(path.parent.glob(f"{path.name}.migration-v3.*.json"))
    assert len(receipts) == 1
    return receipts[0]


def _snapshot(directory: Path) -> dict[str, tuple[bytes, int]]:
    return {
        item.name: (item.read_bytes(), item.stat().st_mtime_ns)
        for item in directory.iterdir()
        if item.is_file()
    }


def test_dry_run_authenticates_and_is_byte_for_byte_read_only(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "fake.vault"
    source = _legacy(path)
    before = _snapshot(tmp_path)
    monkeypatch.setattr(
        "vault_unified.migration.create_v3_container",
        lambda *args, **kwargs: pytest.fail("dry-run must not derive or create V3"),
    )

    outcome = plan_v3_migration(path, LEGACY_PASSWORD)

    assert outcome.action == "dry-run"
    assert outcome.changed is False
    assert outcome.legacy_sha256 == hashlib.sha256(source).hexdigest()
    assert outcome.entry_count == 1
    assert outcome.available_free_bytes >= outcome.required_free_bytes
    assert _snapshot(tmp_path) == before


def test_apply_preserves_exact_legacy_and_activates_equivalent_v3(tmp_path: Path) -> None:
    path = tmp_path / "fake.vault"
    source = _legacy(path)

    outcome = apply_v3_migration(path, LEGACY_PASSWORD, V3_PASSWORD)

    assert outcome.action == "activated"
    assert outcome.changed is True
    assert isinstance(parse_vault_container(path.read_bytes()), V3Container)
    assert decrypt_v3_payload(V3_PASSWORD, path.read_bytes()) == FAKE_PAYLOAD
    assert outcome.backup_path is not None
    assert outcome.backup_path.read_bytes() == source
    assert decrypt_payload(LEGACY_PASSWORD, source) == FAKE_PAYLOAD
    assert outcome.candidate_path is not None
    assert outcome.candidate_path.read_bytes() == path.read_bytes()
    assert outcome.receipt_path is not None
    receipt = load_migration_receipt(outcome.receipt_path)
    assert receipt.state == "activated"
    assert receipt.legacy_sha256 == hashlib.sha256(source).hexdigest()
    assert receipt.candidate_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert receipt.vault_id == parse_vault_container(path.read_bytes()).header.vault_id

    receipt_text = outcome.receipt_path.read_text(encoding="utf-8")
    assert LEGACY_PASSWORD not in receipt_text
    assert V3_PASSWORD not in receipt_text
    assert FAKE_SECRET not in receipt_text
    activation_backup = path.parent / receipt.activation_backup_name
    assert activation_backup.read_bytes() == source


def test_rollback_is_dry_run_then_restores_exact_legacy_and_preserves_v3(
    tmp_path: Path,
) -> None:
    path = tmp_path / "fake.vault"
    source = _legacy(path)
    migrated = apply_v3_migration(path, LEGACY_PASSWORD, V3_PASSWORD)
    receipt_path = migrated.receipt_path
    assert receipt_path is not None
    v3_bytes = path.read_bytes()
    before = _snapshot(tmp_path)

    dry_run = rollback_v3_migration(
        receipt_path,
        LEGACY_PASSWORD,
        V3_PASSWORD,
    )
    assert dry_run.action == "restore-legacy"
    assert dry_run.changed is False
    assert _snapshot(tmp_path) == before

    applied = rollback_v3_migration(
        receipt_path,
        LEGACY_PASSWORD,
        V3_PASSWORD,
        apply=True,
    )
    assert applied.action == "rolled-back"
    assert path.read_bytes() == source
    assert decrypt_payload(LEGACY_PASSWORD, path.read_bytes()) == FAKE_PAYLOAD
    receipt = load_migration_receipt(receipt_path)
    assert receipt.state == "rolled_back"
    rollback_backup = path.parent / receipt.rollback_backup_name
    assert rollback_backup.read_bytes() == v3_bytes
    assert decrypt_v3_payload(V3_PASSWORD, rollback_backup.read_bytes()) == FAKE_PAYLOAD

    repeated = rollback_v3_migration(
        receipt_path,
        LEGACY_PASSWORD,
        V3_PASSWORD,
        apply=True,
    )
    assert repeated.action == "rolled-back"
    assert repeated.changed is False
    assert path.read_bytes() == source


def test_v1_payload_is_normalized_without_changing_secret_fields(tmp_path: Path) -> None:
    path = tmp_path / "legacy-v1.vault"
    payload = {
        "version": 1,
        "entries": {
            "remote-fake": {
                "id": "remote-fake",
                "title": "Old fake",
                "password": FAKE_SECRET,
                "source": "bitwarden",
                "external_id": "fake-external-id",
            }
        },
    }
    path.write_bytes(encrypt_payload(LEGACY_PASSWORD, payload))

    apply_v3_migration(path, LEGACY_PASSWORD, V3_PASSWORD)

    migrated = decrypt_v3_payload(V3_PASSWORD, path.read_bytes())
    entry = migrated["entries"]["remote-fake"]
    assert migrated["version"] == 2
    assert entry["password"] == FAKE_SECRET
    assert entry["linked_sources"] == {"bitwarden": "fake-external-id"}
    assert entry["sync_status"] == "clean"


def test_wrong_password_and_v3_source_create_no_migration_artifacts(tmp_path: Path) -> None:
    path = tmp_path / "fake.vault"
    _legacy(path)
    before = _snapshot(tmp_path)

    with pytest.raises(MigrationError, match="authentication"):
        plan_v3_migration(path, "wrong fake password")
    assert _snapshot(tmp_path) == before

    v3_path = tmp_path / "already-v3.vault"
    create_v3_file(v3_path, V3_PASSWORD, {"version": 2, "entries": {}})
    v3_before = _snapshot(tmp_path)
    with pytest.raises(MigrationError, match="not a legacy"):
        plan_v3_migration(v3_path, V3_PASSWORD)
    assert _snapshot(tmp_path) == v3_before


def test_insufficient_space_stops_before_receipt_or_backup(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "fake.vault"
    _legacy(path)
    before = _snapshot(tmp_path)
    monkeypatch.setattr("vault_unified.migration._free_bytes", lambda _: 0)

    dry_run = plan_v3_migration(path, LEGACY_PASSWORD)
    assert dry_run.available_free_bytes == 0
    assert dry_run.changed is False
    with pytest.raises(MigrationSpaceError, match="only 0"):
        apply_v3_migration(path, LEGACY_PASSWORD, V3_PASSWORD)

    assert _snapshot(tmp_path) == before


@pytest.mark.parametrize("invalid", (float("nan"), float("inf")))
def test_dry_run_rejects_payload_outside_v3_json_contract_without_writes(
    tmp_path: Path,
    invalid: float,
) -> None:
    path = tmp_path / "invalid-json.vault"
    payload = {
        "version": 2,
        "entries": {"fake": {"title": "synthetic", "extra": invalid}},
    }
    path.write_bytes(encrypt_payload(LEGACY_PASSWORD, payload))
    before = _snapshot(tmp_path)

    with pytest.raises(MigrationError, match="exceeds Vault Format v3 bounds"):
        plan_v3_migration(path, LEGACY_PASSWORD)

    assert _snapshot(tmp_path) == before


@pytest.mark.parametrize(
    "event",
    (
        "after_receipt_planned",
        "after_backup_create",
        "after_backup_receipt",
        "after_candidate_create",
        "after_candidate_receipt",
        "after_activation",
        "after_activation_receipt",
    ),
)
def test_every_migration_phase_can_resume_from_durable_evidence(
    tmp_path: Path,
    event: str,
) -> None:
    path = tmp_path / f"fake-{event}.vault"
    source = _legacy(path)

    class InjectedMigrationCrash(RuntimeError):
        pass

    def crash(current: str) -> None:
        if current == event:
            raise InjectedMigrationCrash(current)

    with pytest.raises(InjectedMigrationCrash, match=event):
        apply_v3_migration(
            path,
            LEGACY_PASSWORD,
            V3_PASSWORD,
            _fault_hook=crash,
        )
    receipt_path = _receipt(path)
    before = _snapshot(tmp_path)
    inspection = inspect_v3_migration(receipt_path, LEGACY_PASSWORD, V3_PASSWORD)
    assert inspection.changed is False
    assert _snapshot(tmp_path) == before

    resumed = resume_v3_migration(
        receipt_path,
        LEGACY_PASSWORD,
        V3_PASSWORD,
        apply=True,
    )
    assert resumed.state == "activated"
    assert decrypt_v3_payload(V3_PASSWORD, path.read_bytes()) == FAKE_PAYLOAD
    receipt = load_migration_receipt(receipt_path)
    assert receipt.state == "activated"
    assert (path.parent / receipt.backup_name).read_bytes() == source


def test_unfinished_receipt_blocks_a_second_migration(tmp_path: Path) -> None:
    path = tmp_path / "fake.vault"
    _legacy(path)

    class StopAfterReceipt(RuntimeError):
        pass

    with pytest.raises(StopAfterReceipt):
        apply_v3_migration(
            path,
            LEGACY_PASSWORD,
            V3_PASSWORD,
            _fault_hook=lambda event: (
                (_ for _ in ()).throw(StopAfterReceipt())
                if event == "after_receipt_planned"
                else None
            ),
        )

    with pytest.raises(MigrationError, match="unfinished migration receipt"):
        apply_v3_migration(path, LEGACY_PASSWORD, V3_PASSWORD)


def test_concurrent_live_change_before_activation_is_never_overwritten(
    tmp_path: Path,
) -> None:
    path = tmp_path / "fake.vault"
    _legacy(path)
    competing_path = tmp_path / "competing.vault"
    competing = _legacy(
        competing_path,
        {"version": 2, "entries": {"outside": {"title": "synthetic outside"}}},
    )

    def change_live(event: str) -> None:
        if event == "after_candidate_receipt":
            path.write_bytes(competing)

    with pytest.raises(MigrationError, match="unrecorded version"):
        apply_v3_migration(
            path,
            LEGACY_PASSWORD,
            V3_PASSWORD,
            _fault_hook=change_live,
        )
    assert path.read_bytes() == competing
    with pytest.raises(MigrationError, match="neither the recorded"):
        inspect_v3_migration(_receipt(path), LEGACY_PASSWORD, V3_PASSWORD)


def test_tampered_backup_candidate_and_receipt_fail_without_live_write(
    tmp_path: Path,
) -> None:
    path = tmp_path / "fake.vault"
    _legacy(path)
    outcome = apply_v3_migration(path, LEGACY_PASSWORD, V3_PASSWORD)
    assert outcome.receipt_path and outcome.backup_path and outcome.candidate_path
    live = path.read_bytes()

    outcome.backup_path.write_bytes(b"synthetic tamper")
    with pytest.raises(MigrationError, match="digest"):
        rollback_v3_migration(
            outcome.receipt_path,
            LEGACY_PASSWORD,
            V3_PASSWORD,
        )
    assert path.read_bytes() == live

    path2 = tmp_path / "candidate-tamper.vault"
    _legacy(path2)
    outcome2 = apply_v3_migration(path2, LEGACY_PASSWORD, V3_PASSWORD)
    assert outcome2.receipt_path and outcome2.candidate_path
    outcome2.candidate_path.write_bytes(b"synthetic tamper")
    with pytest.raises(MigrationError, match="digest"):
        inspect_v3_migration(outcome2.receipt_path, LEGACY_PASSWORD, V3_PASSWORD)

    path3 = tmp_path / "receipt-tamper.vault"
    _legacy(path3)
    outcome3 = apply_v3_migration(path3, LEGACY_PASSWORD, V3_PASSWORD)
    assert outcome3.receipt_path
    receipt_json = json.loads(outcome3.receipt_path.read_text(encoding="utf-8"))
    receipt_json["backup_name"] = "..\\outside.vault"
    outcome3.receipt_path.write_text(json.dumps(receipt_json), encoding="utf-8")
    with pytest.raises(MigrationError, match="artifact names"):
        load_migration_receipt(outcome3.receipt_path)


def test_rollback_after_v3_content_change_refuses_data_loss(tmp_path: Path) -> None:
    path = tmp_path / "fake.vault"
    _legacy(path)
    outcome = apply_v3_migration(path, LEGACY_PASSWORD, V3_PASSWORD)
    assert outcome.receipt_path
    changed_payload = {
        "version": 2,
        "entries": {"post-migration": {"title": "must not be lost"}},
    }
    write_encrypted_file(path, V3_PASSWORD, changed_payload)
    changed = path.read_bytes()

    with pytest.raises(MigrationError, match="neither the activated V3"):
        rollback_v3_migration(
            outcome.receipt_path,
            LEGACY_PASSWORD,
            V3_PASSWORD,
            apply=True,
        )
    assert path.read_bytes() == changed
    assert decrypt_v3_payload(V3_PASSWORD, path.read_bytes()) == changed_payload


def test_rollback_crash_after_replace_is_reconciled_without_second_write(
    tmp_path: Path,
) -> None:
    path = tmp_path / "fake.vault"
    source = _legacy(path)
    outcome = apply_v3_migration(path, LEGACY_PASSWORD, V3_PASSWORD)
    assert outcome.receipt_path

    class InjectedRollbackCrash(RuntimeError):
        pass

    with pytest.raises(InjectedRollbackCrash):
        rollback_v3_migration(
            outcome.receipt_path,
            LEGACY_PASSWORD,
            V3_PASSWORD,
            apply=True,
            _fault_hook=lambda event: (
                (_ for _ in ()).throw(InjectedRollbackCrash())
                if event == "after_rollback"
                else None
            ),
        )
    assert path.read_bytes() == source
    before_backups = list_backups(path)

    finalized = rollback_v3_migration(
        outcome.receipt_path,
        LEGACY_PASSWORD,
        V3_PASSWORD,
        apply=True,
    )
    assert finalized.state == "rolled_back"
    assert list_backups(path) == before_backups


def test_cli_migration_and_rollback_are_dry_run_first_and_never_use_keyring(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "cli-fake.vault"
    source = _legacy(path)
    runner = CliRunner()
    monkeypatch.setattr(
        "vault_unified.cli.get_master_password",
        lambda: pytest.fail("migration commands must not read the raw-password keyring"),
    )

    dry = runner.invoke(
        main,
        [
            "migrate-v3",
            "--vault-path",
            str(path),
            "--legacy-password",
            LEGACY_PASSWORD,
        ],
    )
    assert dry.exit_code == 0, dry.output
    assert "Dry-run only" in dry.output
    assert path.read_bytes() == source
    assert list(tmp_path.glob("*.migration-v3.*")) == []

    applied = runner.invoke(
        main,
        [
            "migrate-v3",
            "--apply",
            "--vault-path",
            str(path),
            "--legacy-password",
            LEGACY_PASSWORD,
            "--v3-password",
            V3_PASSWORD,
        ],
    )
    assert applied.exit_code == 0, applied.output
    receipt_path = _receipt(path)
    assert decrypt_v3_payload(V3_PASSWORD, path.read_bytes()) == FAKE_PAYLOAD

    inspected = runner.invoke(
        main,
        [
            "migration",
            "inspect",
            "--receipt",
            str(receipt_path),
            "--legacy-password",
            LEGACY_PASSWORD,
            "--v3-password",
            V3_PASSWORD,
        ],
    )
    assert inspected.exit_code == 0, inspected.output
    assert "complete" in inspected.output

    rollback_dry = runner.invoke(
        main,
        [
            "rollback-v3",
            "--receipt",
            str(receipt_path),
            "--legacy-password",
            LEGACY_PASSWORD,
            "--v3-password",
            V3_PASSWORD,
        ],
    )
    assert rollback_dry.exit_code == 0, rollback_dry.output
    assert "Dry-run only" in rollback_dry.output
    assert isinstance(parse_vault_container(path.read_bytes()), V3Container)

    rolled_back = runner.invoke(
        main,
        [
            "rollback-v3",
            "--apply",
            "--receipt",
            str(receipt_path),
            "--legacy-password",
            LEGACY_PASSWORD,
            "--v3-password",
            V3_PASSWORD,
        ],
    )
    assert rolled_back.exit_code == 0, rolled_back.output
    assert path.read_bytes() == source


def test_interrupted_receipt_update_has_dedicated_dry_run_recovery(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "receipt-recovery.vault"
    _legacy(path)

    class StopAfterPlan(RuntimeError):
        pass

    with pytest.raises(StopAfterPlan):
        apply_v3_migration(
            path,
            LEGACY_PASSWORD,
            V3_PASSWORD,
            _fault_hook=lambda event: (
                (_ for _ in ()).throw(StopAfterPlan())
                if event == "after_receipt_planned"
                else None
            ),
        )
    receipt_path = _receipt(path)

    class ReceiptWriteCrash(RuntimeError):
        pass

    def fault_receipt(target: Path, data: bytes, **kwargs):
        if target == receipt_path:
            def crash(event: str) -> None:
                if event == "after_journal_sync":
                    raise ReceiptWriteCrash(event)

            return atomic_write_bytes(target, data, _fault=crash, **kwargs)
        return atomic_write_bytes(target, data, **kwargs)

    monkeypatch.setattr("vault_unified.migration.atomic_write_bytes", fault_receipt)
    with pytest.raises(ReceiptWriteCrash):
        resume_v3_migration(
            receipt_path,
            LEGACY_PASSWORD,
            V3_PASSWORD,
            apply=True,
        )

    plans = inspect_migration_receipt_recovery(receipt_path)
    assert len(plans) == 1
    assert plans[0].action == "discard_uncommitted"
    before = _snapshot(tmp_path)
    dry = recover_migration_receipt(receipt_path)
    assert dry.action == "discard_uncommitted"
    assert _snapshot(tmp_path) == before

    recover_migration_receipt(receipt_path, apply=True)
    monkeypatch.setattr("vault_unified.migration.atomic_write_bytes", atomic_write_bytes)
    resumed = resume_v3_migration(
        receipt_path,
        LEGACY_PASSWORD,
        V3_PASSWORD,
        apply=True,
    )
    assert resumed.state == "activated"


def test_first_receipt_crash_is_discoverable_recoverable_and_blocks_restart(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "first-receipt-crash.vault"
    source = _legacy(path)

    class InitialReceiptCrash(RuntimeError):
        pass

    def fault_initial_receipt(target: Path, data: bytes, **kwargs):
        if ".migration-v3." in target.name and target.name.endswith(".json"):
            def crash(event: str) -> None:
                if event == "after_journal_sync":
                    raise InitialReceiptCrash(event)

            return atomic_write_bytes(target, data, _fault=crash, **kwargs)
        return atomic_write_bytes(target, data, **kwargs)

    monkeypatch.setattr(
        "vault_unified.migration.atomic_write_bytes",
        fault_initial_receipt,
    )
    with pytest.raises(InitialReceiptCrash):
        apply_v3_migration(path, LEGACY_PASSWORD, V3_PASSWORD)

    assert path.read_bytes() == source
    discovered = discover_migration_receipts(path)
    assert len(discovered) == 1
    receipt_path = discovered[0]
    assert not receipt_path.exists()
    listed = CliRunner().invoke(
        main,
        ["migration", "list", "--vault-path", str(path)],
    )
    assert listed.exit_code == 0, listed.output
    assert "receipt recovery required" in listed.output
    assert str(receipt_path) in listed.output
    plans = inspect_migration_receipt_recovery(receipt_path)
    assert len(plans) == 1
    assert plans[0].action == "restore_new"

    monkeypatch.setattr("vault_unified.migration.atomic_write_bytes", atomic_write_bytes)
    with pytest.raises(MigrationError, match="unfinished migration receipt"):
        apply_v3_migration(path, LEGACY_PASSWORD, V3_PASSWORD)
    recover_migration_receipt(receipt_path, apply=True)
    resumed = resume_v3_migration(
        receipt_path,
        LEGACY_PASSWORD,
        V3_PASSWORD,
        apply=True,
    )
    assert resumed.state == "activated"

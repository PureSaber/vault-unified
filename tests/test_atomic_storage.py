from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import pytest

from vault_unified.crypto import decrypt_payload, read_encrypted_file, write_encrypted_file
from vault_unified.local_store import LocalVault
from vault_unified.models import PrimarySource, SyncPreferences
from vault_unified.storage import (
    RecoveryAmbiguousError,
    RecoveryRequiredError,
    StorageBusyError,
    atomic_write_bytes,
    inspect_recovery,
    list_backups,
    quarantine_stale_lock,
    recover_atomic_file,
    require_clean_storage,
)
from vault_unified.sync_prefs import load_prefs, save_prefs


class InjectedCrash(RuntimeError):
    pass


def _crash_at(expected: str):
    def crash(event: str) -> None:
        if event == expected:
            raise InjectedCrash(event)

    return crash


def test_atomic_replace_keeps_unique_verified_backup(tmp_path: Path) -> None:
    target = tmp_path / "fake.vault"
    target.write_bytes(b"old-fake-bytes")

    receipt = atomic_write_bytes(
        target,
        b"new-fake-bytes",
        validator=lambda data: data.startswith(b"new-"),
    )

    assert target.read_bytes() == b"new-fake-bytes"
    assert receipt.backup_path is not None
    assert receipt.backup_path.read_bytes() == b"old-fake-bytes"
    assert list_backups(target) == [receipt.backup_path]
    assert inspect_recovery(target) == []
    assert not (tmp_path / ".fake.vault.lock").exists()


def test_failure_before_journal_leaves_live_and_no_recovery_artifacts(tmp_path: Path) -> None:
    target = tmp_path / "fake.vault"
    target.write_bytes(b"old")

    with pytest.raises(InjectedCrash, match="after_validation"):
        atomic_write_bytes(target, b"new", _fault=_crash_at("after_validation"))

    assert target.read_bytes() == b"old"
    assert inspect_recovery(target) == []
    assert [item for item in tmp_path.iterdir() if ".tmp." in item.name] == []


@pytest.mark.parametrize(
    ("event", "expected_action", "expected_live"),
    (
        ("after_temp_sync", None, b"old"),
        ("after_validation", None, b"old"),
        ("after_journal_sync", "discard_uncommitted", b"old"),
        ("after_replace", "finalize_committed", b"new"),
        ("after_live_sync", "finalize_committed", b"new"),
        ("after_commit_validation", "finalize_committed", b"new"),
    ),
)
def test_fault_injection_at_every_durable_boundary(
    tmp_path: Path,
    event: str,
    expected_action: str | None,
    expected_live: bytes,
) -> None:
    target = tmp_path / f"{event}.vault"
    target.write_bytes(b"old")

    with pytest.raises(InjectedCrash, match=event):
        atomic_write_bytes(target, b"new", _fault=_crash_at(event))

    assert target.read_bytes() == expected_live
    plans = inspect_recovery(target)
    if expected_action is None:
        assert plans == []
    else:
        assert len(plans) == 1
        assert plans[0].action == expected_action


def test_interrupted_pre_replace_transaction_is_inspect_first(tmp_path: Path) -> None:
    target = tmp_path / "fake.vault"
    target.write_bytes(b"old")

    with pytest.raises(InjectedCrash, match="after_journal_sync"):
        atomic_write_bytes(target, b"new", _fault=_crash_at("after_journal_sync"))

    assert target.read_bytes() == b"old"
    with pytest.raises(RecoveryRequiredError):
        require_clean_storage(target)
    plan = recover_atomic_file(target)
    assert plan.action == "discard_uncommitted"
    assert target.read_bytes() == b"old"  # dry-run is read-only

    applied = recover_atomic_file(target, transaction_id=plan.transaction_id, dry_run=False)
    assert applied.action == "discard_uncommitted"
    assert target.read_bytes() == b"old"
    require_clean_storage(target)


def test_interrupted_post_replace_transaction_finalizes_new_live(tmp_path: Path) -> None:
    target = tmp_path / "fake.vault"
    target.write_bytes(b"old")

    with pytest.raises(InjectedCrash, match="after_replace"):
        atomic_write_bytes(target, b"new", _fault=_crash_at("after_replace"))

    assert target.read_bytes() == b"new"
    plan = recover_atomic_file(target)
    assert plan.action == "finalize_committed"
    assert plan.backup_path is not None
    assert plan.backup_path.read_bytes() == b"old"

    recover_atomic_file(target, transaction_id=plan.transaction_id, dry_run=False)
    assert target.read_bytes() == b"new"
    assert inspect_recovery(target) == []


def test_new_file_can_be_restored_from_synced_temp(tmp_path: Path) -> None:
    target = tmp_path / "fake.vault"

    with pytest.raises(InjectedCrash, match="after_journal_sync"):
        atomic_write_bytes(target, b"new", _fault=_crash_at("after_journal_sync"))

    assert not target.exists()
    plan = recover_atomic_file(target)
    assert plan.action == "restore_new"
    recover_atomic_file(target, transaction_id=plan.transaction_id, dry_run=False)
    assert target.read_bytes() == b"new"


def test_recovery_preserves_unexpected_live_as_pre_recovery_evidence(tmp_path: Path) -> None:
    target = tmp_path / "fake.vault"
    target.write_bytes(b"old")

    with pytest.raises(InjectedCrash):
        atomic_write_bytes(target, b"new", _fault=_crash_at("after_journal_sync"))
    target.write_bytes(b"unexpected-corrupt-evidence")

    plan = recover_atomic_file(target)
    assert plan.action == "restore_new"
    recover_atomic_file(target, transaction_id=plan.transaction_id, dry_run=False)

    assert target.read_bytes() == b"new"
    evidence = tmp_path / f"fake.vault.pre-recovery.{plan.transaction_id}"
    assert evidence.read_bytes() == b"unexpected-corrupt-evidence"


def test_journal_contains_digests_not_payload(tmp_path: Path) -> None:
    target = tmp_path / "fake.vault"
    fake_secret = b"generated-test-secret-only"

    with pytest.raises(InjectedCrash):
        atomic_write_bytes(target, fake_secret, _fault=_crash_at("after_journal_sync"))

    plan = inspect_recovery(target)[0]
    journal_text = plan.journal_path.read_text(encoding="utf-8")
    assert fake_secret.decode() not in journal_text
    assert json.loads(journal_text)["new_sha256"]


def test_tampered_synced_candidate_requires_manual_recovery(tmp_path: Path) -> None:
    target = tmp_path / "fake.vault"
    with pytest.raises(InjectedCrash):
        atomic_write_bytes(target, b"new", _fault=_crash_at("after_journal_sync"))
    plan = inspect_recovery(target)[0]
    assert plan.temp_path is not None
    plan.temp_path.write_bytes(b"tampered")

    inspected = recover_atomic_file(target)
    assert inspected.action == "manual"
    with pytest.raises(RecoveryAmbiguousError):
        recover_atomic_file(target, transaction_id=plan.transaction_id, dry_run=False)
    assert not target.exists()
    assert plan.journal_path.exists()


def test_corrupt_journal_is_never_repaired_implicitly(tmp_path: Path) -> None:
    target = tmp_path / "fake.vault"
    target.write_bytes(b"old")
    transaction_id = "0123456789abcdef0123456789abcdef"
    journal = tmp_path / f".fake.vault.txn.{transaction_id}.json"
    journal.write_text('{"target":"../other"}', encoding="utf-8")

    plan = inspect_recovery(target)[0]
    assert plan.action == "manual"
    with pytest.raises(RecoveryAmbiguousError):
        recover_atomic_file(target, transaction_id=transaction_id, dry_run=False)
    assert target.read_bytes() == b"old"
    assert journal.exists()


def test_existing_lock_blocks_writer_without_overwrite(tmp_path: Path) -> None:
    target = tmp_path / "fake.vault"
    target.write_bytes(b"old")
    (tmp_path / ".fake.vault.lock").write_text("held", encoding="utf-8")

    with pytest.raises(StorageBusyError):
        atomic_write_bytes(target, b"new")
    assert target.read_bytes() == b"old"


def test_concurrent_writer_is_rejected_without_lost_update(tmp_path: Path) -> None:
    target = tmp_path / "fake.vault"
    target.write_bytes(b"old")
    writer_has_lock = threading.Event()
    release_writer = threading.Event()
    failures: list[BaseException] = []

    def pause_after_temp(event: str) -> None:
        if event == "after_temp_sync":
            writer_has_lock.set()
            assert release_writer.wait(timeout=5)

    def first_writer() -> None:
        try:
            atomic_write_bytes(target, b"first", _fault=pause_after_temp)
        except BaseException as exc:  # pragma: no cover - asserted below
            failures.append(exc)

    thread = threading.Thread(target=first_writer)
    thread.start()
    assert writer_has_lock.wait(timeout=5)
    try:
        with pytest.raises(StorageBusyError):
            atomic_write_bytes(target, b"second")
    finally:
        release_writer.set()
        thread.join(timeout=5)

    assert not thread.is_alive()
    assert failures == []
    assert target.read_bytes() == b"first"


def test_stale_lock_is_dry_run_then_quarantined_never_deleted(tmp_path: Path) -> None:
    target = tmp_path / "fake.vault"
    lock = tmp_path / ".fake.vault.lock"
    lock.write_text("stale-evidence", encoding="utf-8")
    old = time.time() - 120
    os.utime(lock, (old, old))

    assert quarantine_stale_lock(target, min_age_seconds=60) == lock
    assert lock.exists()
    quarantined = quarantine_stale_lock(
        target,
        min_age_seconds=60,
        dry_run=False,
    )
    assert not lock.exists()
    assert quarantined.read_text(encoding="utf-8") == "stale-evidence"


def test_encrypted_legacy_writes_roundtrip_and_backup_without_format_change(
    tmp_path: Path,
) -> None:
    target = tmp_path / "fake.vault"
    password = "generated-fake-password"
    old = {"version": 2, "entries": {}}
    new = {"version": 2, "entries": {"fake": {"title": "fixture"}}}

    write_encrypted_file(target, password, old)
    write_encrypted_file(target, password, new)

    assert read_encrypted_file(target, password) == new
    assert not target.read_bytes().startswith(b"VLTUV3\r\n")
    backup = list_backups(target)[0]
    assert decrypt_payload(password, backup.read_bytes()) == old


def test_opening_legacy_vault_is_byte_for_byte_read_only(tmp_path: Path) -> None:
    target = tmp_path / "fake.vault"
    password = "generated-fake-password"
    payload = {"version": 2, "entries": {}}
    write_encrypted_file(target, password, payload)
    before = target.read_bytes()

    LocalVault(target, password)

    assert target.read_bytes() == before
    assert list_backups(target) == []


@pytest.mark.parametrize("size", (0, 1, 4096, 65536))
def test_generated_byte_lengths_roundtrip_atomically(tmp_path: Path, size: int) -> None:
    target = tmp_path / f"fake-{size}.bin"
    data = bytes(index % 251 for index in range(size))

    atomic_write_bytes(target, data, validator=lambda candidate: candidate == data)

    assert target.read_bytes() == data


def test_sync_preferences_use_atomic_backup(tmp_path: Path) -> None:
    vault_path = tmp_path / "fake.vault"
    first = SyncPreferences(primary=PrimarySource.LOCAL, auto_push_on_edit=True)
    second = SyncPreferences(primary=PrimarySource.LOCAL, auto_push_on_edit=False)

    save_prefs(vault_path, first)
    save_prefs(vault_path, second)

    assert load_prefs(vault_path).auto_push_on_edit is False
    backups = list_backups(tmp_path / "sync_prefs.json")
    assert len(backups) == 1
    assert json.loads(backups[0].read_text(encoding="utf-8"))["auto_push_on_edit"] is True

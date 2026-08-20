from __future__ import annotations

import base64
import copy
import hashlib
import json
import math
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner
from cryptography.exceptions import UnsupportedAlgorithm

from vault_unified.api.routes.auth import check_keyring
from vault_unified.cli import main
from vault_unified.crypto import (
    decrypt_payload,
    inspect_encrypted_file_recovery,
    write_encrypted_file,
)
from vault_unified.local_store import LocalVault
from vault_unified.models import SecretEntry
from vault_unified.session import SessionManager
from vault_unified.storage import (
    ConcurrentStorageChangeError,
    atomic_write_bytes,
    list_backups,
)
from vault_unified.v3_crypto import (
    V3AuthenticationError,
    V3CreationMaterials,
    V3CryptoError,
    V3CryptoUnavailableError,
    V3PasswordSlotSelectionRequired,
    V3PayloadError,
    _create_v3_container_with_materials,
    _parse_plaintext,
    create_v3_container,
    create_v3_file,
    decrypt_v3_payload,
    rotate_v3_dek,
    rotate_v3_password,
    rotate_v3_password_file,
    update_v3_container,
)
from vault_unified.vault_format import V3Container, V3_MAGIC, parse_vault_container


FAKE_PASSWORD = "correct horse fake fixture"
FAKE_NEW_PASSWORD = "new generated fake fixture password"
FAKE_PAYLOAD = {
    "version": 2,
    "entries": {
        "fake-entry": {
            "title": "Synthetic only",
            "username": "nobody@example.invalid",
            "password": "not-a-real-secret",
        }
    },
}
FIXED_MATERIALS = V3CreationMaterials(
    vault_id="11111111-1111-4111-8111-111111111111",
    dek_id="22222222-2222-4222-8222-222222222222",
    slot_id="33333333-3333-4333-8333-333333333333",
    salt=bytes(range(16)),
    wrap_nonce=bytes(range(16, 28)),
    payload_nonce=bytes(range(28, 40)),
    dek=bytes(range(32)),
)
ROTATED_MATERIALS = V3CreationMaterials(
    vault_id=FIXED_MATERIALS.vault_id,
    dek_id="44444444-4444-4444-8444-444444444444",
    slot_id="55555555-5555-4555-8555-555555555555",
    salt=bytes(range(40, 56)),
    wrap_nonce=bytes(range(56, 68)),
    payload_nonce=bytes(range(68, 80)),
    dek=bytes(range(32, 64)),
)


@pytest.fixture(scope="module")
def known_frame() -> bytes:
    return _create_v3_container_with_materials(
        FAKE_PASSWORD,
        FAKE_PAYLOAD,
        FIXED_MATERIALS,
        extensions={"example.org:fixture": True},
    )


def _reframe(value: bytes, change_header=None, change_ciphertext=None) -> bytes:
    parsed = parse_vault_container(value)
    assert isinstance(parsed, V3Container)
    header = json.loads(parsed.raw_header)
    if change_header is not None:
        change_header(header)
    ciphertext = parsed.ciphertext
    if change_ciphertext is not None:
        ciphertext = change_ciphertext(ciphertext)
    raw = json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return V3_MAGIC + len(raw).to_bytes(4, "big") + raw + ciphertext


def _flip(value: bytes) -> bytes:
    return bytes([value[0] ^ 1]) + value[1:]


def test_known_materials_are_deterministic_and_roundtrip(known_frame: bytes) -> None:
    second = _create_v3_container_with_materials(
        FAKE_PASSWORD,
        FAKE_PAYLOAD,
        FIXED_MATERIALS,
        extensions={"example.org:fixture": True},
    )

    assert second == known_frame
    assert decrypt_v3_payload(FAKE_PASSWORD, known_frame) == FAKE_PAYLOAD
    parsed = parse_vault_container(known_frame)
    assert isinstance(parsed, V3Container)
    assert parsed.header.generation == 1
    assert parsed.header.key_generation == 1
    assert parsed.header.key_slots[0].kdf.memory_kib == 65_536
    assert parsed.header.key_slots[0].kdf.passes == 3
    assert parsed.header.key_slots[0].kdf.lanes == 4


def test_published_synthetic_known_answer_vector_is_stable() -> None:
    vector = json.loads(
        (Path(__file__).parent / "fixtures" / "v3-known-answer.json").read_text(
            encoding="utf-8"
        )
    )
    material = vector["materials"]
    materials = V3CreationMaterials(
        vault_id=material["vault_id"],
        dek_id=material["dek_id"],
        slot_id=material["slot_id"],
        salt=bytes.fromhex(material["salt_hex"]),
        wrap_nonce=bytes.fromhex(material["wrap_nonce_hex"]),
        payload_nonce=bytes.fromhex(material["payload_nonce_hex"]),
        dek=bytes.fromhex(material["dek_hex"]),
    )

    frame = _create_v3_container_with_materials(
        vector["password"],
        vector["payload"],
        materials,
        extensions=vector["extensions"],
    )

    assert len(frame) == vector["expected"]["bytes"]
    assert hashlib.sha256(frame).hexdigest() == vector["expected"]["sha256"]
    assert base64.b64encode(frame).decode("ascii") == vector["expected"]["frame_base64"]
    assert decrypt_v3_payload(vector["password"], frame) == vector["payload"]


def test_wrong_password_is_normalized(known_frame: bytes) -> None:
    with pytest.raises(V3AuthenticationError, match="Wrong password or tampered"):
        decrypt_v3_payload("wrong fake password", known_frame)


@pytest.mark.parametrize(
    "mutator",
    (
        lambda header: header.__setitem__(
            "vault_id", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        ),
        lambda header: header.__setitem__("generation", 2),
        lambda header: header["key_slots"][0].__setitem__(
            "wrapped_dek",
            base64.urlsafe_b64encode(b"x" * 48).rstrip(b"=").decode("ascii"),
        ),
    ),
)
def test_authenticated_header_tampering_fails(known_frame: bytes, mutator) -> None:
    with pytest.raises(V3AuthenticationError):
        decrypt_v3_payload(FAKE_PASSWORD, _reframe(known_frame, mutator))


def test_ciphertext_tampering_fails(known_frame: bytes) -> None:
    damaged = _reframe(known_frame, change_ciphertext=_flip)
    with pytest.raises(V3AuthenticationError, match="payload"):
        decrypt_v3_payload(FAKE_PASSWORD, damaged)


def test_update_reuses_dek_but_advances_generation_and_nonce(known_frame: bytes) -> None:
    new_payload = {"version": 2, "entries": {}}
    updated = update_v3_container(
        FAKE_PASSWORD,
        new_payload,
        known_frame,
        _payload_nonce=b"n" * 12,
    )
    before = parse_vault_container(known_frame)
    after = parse_vault_container(updated)
    assert isinstance(before, V3Container)
    assert isinstance(after, V3Container)

    assert decrypt_v3_payload(FAKE_PASSWORD, updated) == new_payload
    assert after.header.generation == before.header.generation + 1
    assert after.header.key_generation == before.header.key_generation
    assert after.header.dek_id == before.header.dek_id
    assert after.header.payload_nonce == b"n" * 12
    assert after.ciphertext != before.ciphertext


def test_update_forbids_payload_nonce_reuse(known_frame: bytes) -> None:
    parsed = parse_vault_container(known_frame)
    assert isinstance(parsed, V3Container)
    with pytest.raises(V3CryptoError, match="reuse"):
        update_v3_container(
            FAKE_PASSWORD,
            FAKE_PAYLOAD,
            known_frame,
            _payload_nonce=parsed.header.payload_nonce,
        )


def test_password_rotation_rewraps_only_and_invalidates_old_password(
    known_frame: bytes,
) -> None:
    rotated = rotate_v3_password(
        FAKE_PASSWORD,
        FAKE_NEW_PASSWORD,
        known_frame,
        _materials=ROTATED_MATERIALS,
    )
    before = parse_vault_container(known_frame)
    after = parse_vault_container(rotated)
    assert isinstance(before, V3Container)
    assert isinstance(after, V3Container)

    assert decrypt_v3_payload(FAKE_NEW_PASSWORD, rotated) == FAKE_PAYLOAD
    with pytest.raises(V3AuthenticationError):
        decrypt_v3_payload(FAKE_PASSWORD, rotated)
    assert after.ciphertext == before.ciphertext
    assert after.header.generation == before.header.generation
    assert after.header.key_generation == before.header.key_generation + 1
    assert after.header.dek_id == before.header.dek_id
    assert after.header.payload_nonce == before.header.payload_nonce


def test_dek_rotation_reencrypts_and_advances_both_generations(
    known_frame: bytes,
) -> None:
    rotated = rotate_v3_dek(
        FAKE_PASSWORD,
        known_frame,
        _materials=ROTATED_MATERIALS,
    )
    before = parse_vault_container(known_frame)
    after = parse_vault_container(rotated)
    assert isinstance(before, V3Container)
    assert isinstance(after, V3Container)

    assert decrypt_v3_payload(FAKE_PASSWORD, rotated) == FAKE_PAYLOAD
    assert after.header.vault_id == before.header.vault_id
    assert after.header.dek_id == ROTATED_MATERIALS.dek_id
    assert after.header.dek_id != before.header.dek_id
    assert after.header.generation == before.header.generation + 1
    assert after.header.key_generation == before.header.key_generation + 1
    assert after.ciphertext != before.ciphertext


def test_v3_file_updates_atomically_and_backup_opens_with_old_state(tmp_path: Path) -> None:
    path = tmp_path / "fake-v3.vault"
    create_v3_file(path, FAKE_PASSWORD, {"version": 2, "entries": {}})
    original = path.read_bytes()

    write_encrypted_file(path, FAKE_PASSWORD, FAKE_PAYLOAD)

    assert path.read_bytes().startswith(V3_MAGIC)
    assert decrypt_payload(FAKE_PASSWORD, path.read_bytes()) == FAKE_PAYLOAD
    backups = list_backups(path)
    assert len(backups) == 1
    assert backups[0].read_bytes() == original
    assert decrypt_v3_payload(FAKE_PASSWORD, backups[0].read_bytes()) == {
        "version": 2,
        "entries": {},
    }


def test_password_rotation_backup_remains_recoverable_with_old_password(
    tmp_path: Path,
) -> None:
    path = tmp_path / "fake-v3.vault"
    create_v3_file(path, FAKE_PASSWORD, FAKE_PAYLOAD)

    rotate_v3_password_file(path, FAKE_PASSWORD, FAKE_NEW_PASSWORD)

    assert decrypt_v3_payload(FAKE_NEW_PASSWORD, path.read_bytes()) == FAKE_PAYLOAD
    backup = list_backups(path)[0]
    assert decrypt_v3_payload(FAKE_PASSWORD, backup.read_bytes()) == FAKE_PAYLOAD


def test_explicit_v3_creation_refuses_existing_and_legacy_create_stays_legacy(
    tmp_path: Path,
) -> None:
    v3_path = tmp_path / "v3.vault"
    create_v3_file(v3_path, FAKE_PASSWORD, {"version": 2, "entries": {}})
    before = v3_path.read_bytes()
    with pytest.raises(FileExistsError):
        create_v3_file(v3_path, FAKE_PASSWORD, FAKE_PAYLOAD)
    assert v3_path.read_bytes() == before

    legacy_path = tmp_path / "legacy.vault"
    LocalVault.create(legacy_path, FAKE_PASSWORD)
    assert not legacy_path.read_bytes().startswith(V3_MAGIC)


def test_v3_create_refuses_target_that_appears_during_candidate_build(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "raced-create.vault"
    competing = b"synthetic competing writer"

    def race(target: Path, data: bytes, **kwargs):
        target.write_bytes(competing)
        return atomic_write_bytes(target, data, **kwargs)

    monkeypatch.setattr("vault_unified.v3_crypto.atomic_write_bytes", race)
    with pytest.raises(FileExistsError, match="appeared"):
        create_v3_file(path, FAKE_PASSWORD, {"version": 2, "entries": {}})
    assert path.read_bytes() == competing
    assert list_backups(path) == []


def test_v3_update_refuses_lost_update_race(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "raced-update.vault"
    create_v3_file(path, FAKE_PASSWORD, {"version": 2, "entries": {}})
    competing = create_v3_container(
        FAKE_PASSWORD,
        {"version": 2, "entries": {"competing": {"title": "fake"}}},
    )

    def race(target: Path, data: bytes, **kwargs):
        target.write_bytes(competing)
        return atomic_write_bytes(target, data, **kwargs)

    monkeypatch.setattr("vault_unified.v3_crypto.atomic_write_bytes", race)
    with pytest.raises(ConcurrentStorageChangeError, match="changed"):
        write_encrypted_file(path, FAKE_PASSWORD, FAKE_PAYLOAD)
    assert path.read_bytes() == competing
    assert list_backups(path) == []


def test_interrupted_v3_update_preserves_live_and_has_deterministic_recovery(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "interrupted-v3.vault"
    create_v3_file(path, FAKE_PASSWORD, {"version": 2, "entries": {}})
    original = path.read_bytes()

    class InjectedCrash(RuntimeError):
        pass

    def faulted(target: Path, data: bytes, **kwargs):
        def crash(event: str) -> None:
            if event == "after_journal_sync":
                raise InjectedCrash(event)

        return atomic_write_bytes(target, data, _fault=crash, **kwargs)

    monkeypatch.setattr("vault_unified.v3_crypto.atomic_write_bytes", faulted)
    with pytest.raises(InjectedCrash, match="after_journal_sync"):
        write_encrypted_file(path, FAKE_PASSWORD, FAKE_PAYLOAD)

    assert path.read_bytes() == original
    plans = inspect_encrypted_file_recovery(path, FAKE_PASSWORD)
    assert len(plans) == 1
    assert plans[0].action == "discard_uncommitted"


def test_noncooperative_change_before_replace_is_never_overwritten(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "noncooperative-v3.vault"
    create_v3_file(path, FAKE_PASSWORD, {"version": 2, "entries": {}})
    competing = create_v3_container(
        FAKE_PASSWORD,
        {"version": 2, "entries": {"outside": {"title": "synthetic"}}},
    )

    def contested(target: Path, data: bytes, **kwargs):
        def change_live(event: str) -> None:
            if event == "after_journal_sync":
                target.write_bytes(competing)

        return atomic_write_bytes(target, data, _fault=change_live, **kwargs)

    monkeypatch.setattr("vault_unified.v3_crypto.atomic_write_bytes", contested)
    with pytest.raises(ConcurrentStorageChangeError, match="immediately before"):
        write_encrypted_file(path, FAKE_PASSWORD, FAKE_PAYLOAD)

    assert path.read_bytes() == competing
    plans = inspect_encrypted_file_recovery(path, FAKE_PASSWORD)
    assert len(plans) == 1
    assert plans[0].action == "manual"


def test_local_vault_can_edit_an_explicit_v3_file(tmp_path: Path) -> None:
    path = tmp_path / "fake-v3.vault"
    create_v3_file(path, FAKE_PASSWORD, {"version": 2, "entries": {}})
    vault = LocalVault(path, FAKE_PASSWORD)

    entry = vault.add(SecretEntry(title="Synthetic", password="fake-value"))

    reopened = LocalVault(path, FAKE_PASSWORD)
    assert reopened.get(entry.id).password == "fake-value"
    assert path.read_bytes().startswith(V3_MAGIC)


@pytest.mark.parametrize("bad_password", ("", "x" * 1025))
def test_password_utf8_length_is_bounded(bad_password: str) -> None:
    with pytest.raises(V3CryptoError, match="1-1024"):
        create_v3_container(bad_password, {"version": 2, "entries": {}})


@pytest.mark.parametrize("bad_value", (math.nan, math.inf, -math.inf))
def test_non_finite_json_is_rejected_before_encryption(bad_value: float) -> None:
    payload = {"version": 2, "entries": {"fake": {"value": bad_value}}}
    with pytest.raises(V3PayloadError, match="finite JSON"):
        create_v3_container(FAKE_PASSWORD, payload)


def test_non_finite_authenticated_json_is_rejected_on_decode() -> None:
    plaintext = b'{"entries":{"fake":NaN},"version":2}'
    with pytest.raises(V3PayloadError, match="non-finite"):
        _parse_plaintext(plaintext, len(plaintext))


def test_invalid_unicode_and_non_string_object_names_are_rejected() -> None:
    with pytest.raises(V3PayloadError, match="valid Unicode"):
        create_v3_container(
            FAKE_PASSWORD,
            {"version": 2, "entries": {"fake": {"value": "\ud800"}}},
        )
    with pytest.raises(V3PayloadError, match="names must be strings"):
        create_v3_container(
            FAKE_PASSWORD,
            {"version": 2, "entries": {1: {"value": "fake"}}},
        )


def test_reference_cycles_and_excessive_depth_are_rejected() -> None:
    cyclic: dict = {"version": 2, "entries": {}}
    cyclic["entries"]["cycle"] = cyclic
    with pytest.raises(V3PayloadError, match="reference cycle"):
        create_v3_container(FAKE_PASSWORD, cyclic)

    nested: dict = {}
    root = nested
    for _ in range(40):
        child: dict = {}
        nested["next"] = child
        nested = child
    with pytest.raises(V3PayloadError, match="depth"):
        create_v3_container(
            FAKE_PASSWORD,
            {"version": 2, "entries": {"deep": root}},
        )


def test_multiple_password_slots_require_reviewed_selection(known_frame: bytes) -> None:
    def duplicate_slot(header: dict) -> None:
        slot = copy.deepcopy(header["key_slots"][0])
        slot["slot_id"] = "66666666-6666-4666-8666-666666666666"
        header["key_slots"].append(slot)

    multiple = _reframe(known_frame, duplicate_slot)
    with pytest.raises(V3PasswordSlotSelectionRequired):
        decrypt_v3_payload(FAKE_PASSWORD, multiple)


def test_argon2_backend_failure_is_normalized() -> None:
    with patch(
        "vault_unified.v3_crypto.Argon2id",
        side_effect=UnsupportedAlgorithm("synthetic unsupported backend"),
    ):
        with pytest.raises(V3CryptoUnavailableError, match="cryptography >=44"):
            create_v3_container(FAKE_PASSWORD, {"version": 2, "entries": {}})


def test_session_v3_remember_refuses_before_keyring_write(tmp_path: Path) -> None:
    path = tmp_path / "fake-v3.vault"
    create_v3_file(path, FAKE_PASSWORD, {"version": 2, "entries": {}})
    manager = SessionManager()

    with patch("vault_unified.session.save_master_password") as save:
        with pytest.raises(ValueError, match="device slots"):
            manager.unlock(FAKE_PASSWORD, vault_path=path, remember=True)
    save.assert_not_called()


def test_session_v3_never_reads_legacy_keyring_password(tmp_path: Path) -> None:
    path = tmp_path / "fake-v3.vault"
    create_v3_file(path, FAKE_PASSWORD, {"version": 2, "entries": {}})
    manager = SessionManager()

    with patch("vault_unified.session.get_master_password") as get_saved:
        with pytest.raises(ValueError, match="required"):
            manager.unlock(vault_path=path)
    get_saved.assert_not_called()


def test_v3_keyring_probe_does_not_read_legacy_raw_password(tmp_path: Path) -> None:
    path = tmp_path / "fake-v3.vault"
    create_v3_file(path, FAKE_PASSWORD, {"version": 2, "entries": {}})

    with patch("vault_unified.api.routes.auth.require_loopback"), patch(
        "vault_unified.api.routes.auth.get_vault_path", return_value=path
    ), patch("vault_unified.keyring_store.get_master_password") as get_saved:
        result = check_keyring(object())

    assert result == {"has_saved_password": False}
    get_saved.assert_not_called()


def test_cli_explicit_v3_create_and_rotations_use_only_fake_inputs(tmp_path: Path) -> None:
    path = tmp_path / "cli-fake-v3.vault"
    runner = CliRunner()
    with patch("vault_unified.cli.get_master_password") as get_saved, patch(
        "vault_unified.cli.save_master_password"
    ) as save:
        created = runner.invoke(
            main,
            ["init-v3", "--vault-path", str(path), "--password", FAKE_PASSWORD],
        )
        changed = runner.invoke(
            main,
            [
                "v3",
                "rotate-password",
                "--vault-path",
                str(path),
                "--old-password",
                FAKE_PASSWORD,
                "--new-password",
                FAKE_NEW_PASSWORD,
            ],
        )
        rotated = runner.invoke(
            main,
            [
                "v3",
                "rotate-dek",
                "--vault-path",
                str(path),
                "--password",
                FAKE_NEW_PASSWORD,
            ],
        )

    assert created.exit_code == 0, created.output
    assert changed.exit_code == 0, changed.output
    assert rotated.exit_code == 0, rotated.output
    assert decrypt_v3_payload(FAKE_NEW_PASSWORD, path.read_bytes()) == {
        "version": 2,
        "entries": {},
    }
    get_saved.assert_not_called()
    save.assert_not_called()


def test_cli_v3_open_failure_and_status_never_read_legacy_keyring(tmp_path: Path) -> None:
    path = tmp_path / "cli-fake-v3.vault"
    create_v3_file(path, FAKE_PASSWORD, {"version": 2, "entries": {}})
    runner = CliRunner()

    with patch("vault_unified.cli.get_master_password") as get_saved, patch(
        "vault_unified.cli.is_remember_enabled"
    ) as remember, patch(
        "vault_unified.cli.getpass.getpass", return_value="wrong synthetic password"
    ):
        failed = runner.invoke(main, ["list", "--vault-path", str(path)])
        status = runner.invoke(
            main,
            ["status", "--vault-path", str(path), "--password", FAKE_PASSWORD],
        )

    assert failed.exit_code == 1, failed.output
    assert "Wrong password or corrupted vault" in failed.output
    assert status.exit_code == 0, status.output
    assert "disabled for v3 until device slots ship" in status.output
    get_saved.assert_not_called()
    remember.assert_not_called()

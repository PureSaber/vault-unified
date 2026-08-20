from __future__ import annotations

import base64
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from vault_unified.cli import main
from vault_unified.crypto import read_encrypted_file, write_encrypted_file
from vault_unified.device_keyring import (
    ANCHOR_SERVICE,
    DEVICE_SERVICE,
    DeviceKeyringCleanupRequired,
    DeviceKeyringError,
    UnapprovedKeyringBackend,
    V3RollbackDetected,
    disable_device_unlock,
    disable_rollback_anchor,
    enable_device_unlock,
    enable_rollback_anchor,
    validate_production_backend,
)
from vault_unified.manager import UnifiedVault
from vault_unified.session import SessionManager
from vault_unified.v3_crypto import (
    ROLLBACK_ANCHOR_EXTENSION,
    V3CryptoError,
    V3AuthenticationError,
    decrypt_v3_payload,
    rotate_v3_dek,
    rotate_v3_password,
    update_v3_extensions,
)
from vault_unified.vault_format import (
    DeviceSlotHeader,
    PasswordSlotHeader,
    V3Container,
    V3_MAGIC,
    VaultFormatError,
    parse_vault_container,
)


FAKE_PASSWORD = "generated-5e-password"
FAKE_NEW_PASSWORD = "generated-5e-new-password"
FAKE_PAYLOAD = {"version": 2, "entries": {}}


class MemoryBackend:
    def __init__(self) -> None:
        self.records: dict[tuple[str, str], str] = {}
        self.written_values: list[str] = []
        self.calls: list[tuple[str, str, str]] = []
        self.fail_delete = False

    def get_password(self, service: str, username: str) -> str | None:
        self.calls.append(("get", service, username))
        return self.records.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.calls.append(("set", service, username))
        self.written_values.append(password)
        self.records[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self.calls.append(("delete", service, username))
        if self.fail_delete:
            raise RuntimeError("synthetic delete failure")
        if self.records.pop((service, username), None) is None:
            raise RuntimeError("synthetic missing record")


@pytest.fixture
def backend() -> MemoryBackend:
    return MemoryBackend()


@pytest.fixture
def v3_path(tmp_path: Path) -> Path:
    from vault_unified.v3_crypto import create_v3_file

    path = tmp_path / "synthetic-5e.vault"
    create_v3_file(path, FAKE_PASSWORD, FAKE_PAYLOAD)
    return path


def _approved(backend: MemoryBackend):
    return patch("vault_unified.device_keyring.get_approved_backend", return_value=backend)


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _mutate_header(frame: bytes, mutation) -> bytes:
    start = len(V3_MAGIC) + 4
    length = int.from_bytes(frame[len(V3_MAGIC) : start], "big")
    header = json.loads(frame[start : start + length])
    mutation(header)
    encoded = json.dumps(header, sort_keys=True, separators=(",", ":")).encode()
    return V3_MAGIC + len(encoded).to_bytes(4, "big") + encoded + frame[start + length :]


def test_production_backend_allowlist_is_exact() -> None:
    approved_type = type("WinVaultKeyring", (), {})
    approved_type.__module__ = "keyring.backends.Windows"
    approved = approved_type()

    assert validate_production_backend(approved, system_name="Windows") is approved
    with pytest.raises(UnapprovedKeyringBackend):
        validate_production_backend(MemoryBackend(), system_name="Windows")
    with pytest.raises(UnapprovedKeyringBackend):
        validate_production_backend(approved, system_name="Linux")


def test_device_enable_roundtrip_edit_and_disable(
    v3_path: Path, backend: MemoryBackend
) -> None:
    with _approved(backend):
        credential = enable_device_unlock(v3_path, FAKE_PASSWORD)

        parsed = parse_vault_container(v3_path.read_bytes())
        assert isinstance(parsed, V3Container)
        assert [type(slot) for slot in parsed.header.key_slots] == [
            PasswordSlotHeader,
            DeviceSlotHeader,
        ]
        assert decrypt_v3_payload(FAKE_PASSWORD, parsed) == FAKE_PAYLOAD
        assert decrypt_v3_payload(credential, parsed) == FAKE_PAYLOAD
        stored_values = list(backend.records.values())
        assert len(stored_values) == 1
        assert FAKE_PASSWORD not in stored_values

        vault = UnifiedVault(v3_path, credential)
        entry = vault.add(
            "synthetic-device-entry",
            "fake-user",
            "fake-entry-secret",
            auto_push=False,
        )
        assert decrypt_v3_payload(FAKE_PASSWORD, v3_path.read_bytes())["entries"][
            entry.id
        ]["title"] == "synthetic-device-entry"

        disable_device_unlock(v3_path, FAKE_PASSWORD)

    final = parse_vault_container(v3_path.read_bytes())
    assert isinstance(final, V3Container)
    assert all(isinstance(slot, PasswordSlotHeader) for slot in final.header.key_slots)
    assert not backend.records


def test_enable_writes_keyring_before_file_and_cleans_up_on_activation_failure(
    v3_path: Path, backend: MemoryBackend
) -> None:
    events: list[str] = []
    real_set = backend.set_password

    def tracked_set(service: str, username: str, password: str) -> None:
        events.append("keyring-set")
        real_set(service, username, password)

    backend.set_password = tracked_set  # type: ignore[method-assign]
    original = v3_path.read_bytes()
    with _approved(backend), patch(
        "vault_unified.device_keyring.atomic_write_bytes",
        side_effect=lambda *args, **kwargs: events.append("file-write")
        or (_ for _ in ()).throw(RuntimeError("synthetic activation failure")),
    ):
        with pytest.raises(DeviceKeyringError, match="before vault activation"):
            enable_device_unlock(v3_path, FAKE_PASSWORD)

    assert events == ["keyring-set", "file-write"]
    assert v3_path.read_bytes() == original
    assert not backend.records


def test_enable_cleanup_failure_is_explicit(
    v3_path: Path, backend: MemoryBackend
) -> None:
    backend.fail_delete = True
    with _approved(backend), patch(
        "vault_unified.device_keyring.atomic_write_bytes",
        side_effect=RuntimeError("synthetic activation failure"),
    ):
        with pytest.raises(DeviceKeyringCleanupRequired, match="orphan"):
            enable_device_unlock(v3_path, FAKE_PASSWORD)
    assert len(backend.records) == 1


def test_disable_activates_password_only_file_before_external_delete_failure(
    v3_path: Path, backend: MemoryBackend
) -> None:
    with _approved(backend):
        enable_device_unlock(v3_path, FAKE_PASSWORD)
        backend.fail_delete = True
        with pytest.raises(DeviceKeyringCleanupRequired, match="orphan"):
            disable_device_unlock(v3_path, FAKE_PASSWORD)

    parsed = parse_vault_container(v3_path.read_bytes())
    assert isinstance(parsed, V3Container)
    assert not any(isinstance(slot, DeviceSlotHeader) for slot in parsed.header.key_slots)
    assert decrypt_v3_payload(FAKE_PASSWORD, parsed)["version"] == 2


def test_key_rotations_fail_closed_while_device_slot_exists(
    v3_path: Path, backend: MemoryBackend
) -> None:
    with _approved(backend):
        enable_device_unlock(v3_path, FAKE_PASSWORD)
    source = v3_path.read_bytes()

    with pytest.raises(V3CryptoError, match="Disable device unlock"):
        rotate_v3_password(FAKE_PASSWORD, FAKE_NEW_PASSWORD, source)
    with pytest.raises(V3CryptoError, match="Disable device unlock"):
        rotate_v3_dek(FAKE_PASSWORD, source)
    assert v3_path.read_bytes() == source


def test_device_slot_backend_and_wrapped_key_tampering_fail_closed(
    v3_path: Path, backend: MemoryBackend
) -> None:
    with _approved(backend):
        credential = enable_device_unlock(v3_path, FAKE_PASSWORD)
    source = v3_path.read_bytes()

    unsupported = _mutate_header(
        source,
        lambda header: header["key_slots"][1].__setitem__(
            "keyring_backend", "plaintext-file"
        ),
    )
    with pytest.raises(VaultFormatError, match="Unsupported device keyring"):
        parse_vault_container(unsupported)

    tampered = _mutate_header(
        source,
        lambda header: header["key_slots"][1].__setitem__(
            "wrapped_dek", _b64(b"x" * 48)
        ),
    )
    with pytest.raises(V3AuthenticationError):
        decrypt_v3_payload(credential, tampered)


def test_session_remember_and_passwordless_unlock_use_device_credential(
    v3_path: Path, backend: MemoryBackend
) -> None:
    manager = SessionManager()
    with _approved(backend), patch("vault_unified.session.save_master_password") as legacy:
        first_token, _ = manager.unlock(
            FAKE_PASSWORD, vault_path=v3_path, remember=True
        )
        manager.lock(first_token)
        second_token, vault = manager.unlock(vault_path=v3_path)
        vault.add("session-device-entry", auto_push=False)

    legacy.assert_not_called()
    assert manager.is_unlocked(second_token)
    assert any(
        item[0] == "get" and item[1] == DEVICE_SERVICE for item in backend.calls
    )
    assert len(decrypt_v3_payload(FAKE_PASSWORD, v3_path.read_bytes())["entries"]) == 1


def test_device_session_fails_closed_for_legacy_conflict_sidecar(
    v3_path: Path, backend: MemoryBackend
) -> None:
    sidecar = v3_path.parent / "conflicts.vault"
    write_encrypted_file(sidecar, FAKE_PASSWORD, {"conflicts": []})
    with _approved(backend):
        enable_device_unlock(v3_path, FAKE_PASSWORD)
        with pytest.raises(ValueError, match="legacy conflict sidecar"):
            SessionManager().unlock(vault_path=v3_path)

    assert read_encrypted_file(sidecar, FAKE_PASSWORD) == {"conflicts": []}


def test_anchor_advances_and_blocks_older_authenticated_file(
    v3_path: Path, backend: MemoryBackend
) -> None:
    with _approved(backend):
        enable_rollback_anchor(v3_path, FAKE_PASSWORD)
        anchored = v3_path.read_bytes()
        write_encrypted_file(
            v3_path,
            FAKE_PASSWORD,
            {"version": 2, "entries": {"synthetic": {"title": "fake"}}},
        )
        assert read_encrypted_file(v3_path, FAKE_PASSWORD)["version"] == 2
        v3_path.write_bytes(anchored)
        with pytest.raises(V3RollbackDetected, match="rollback"):
            read_encrypted_file(v3_path, FAKE_PASSWORD)


def test_anchor_blocks_same_generation_digest_conflict(
    v3_path: Path, backend: MemoryBackend
) -> None:
    source = v3_path.read_bytes()
    alternate = update_v3_extensions(
        FAKE_PASSWORD,
        source,
        {ROLLBACK_ANCHOR_EXTENSION: True, "example.org:alternate": True},
    )
    with _approved(backend):
        enable_rollback_anchor(v3_path, FAKE_PASSWORD)
        v3_path.write_bytes(alternate)
        with pytest.raises(V3RollbackDetected, match="digest"):
            read_encrypted_file(v3_path, FAKE_PASSWORD)


def test_missing_anchor_degrades_without_losing_password_recovery(
    v3_path: Path, backend: MemoryBackend
) -> None:
    with _approved(backend):
        anchor = enable_rollback_anchor(v3_path, FAKE_PASSWORD)
        encoded = backend.records[(ANCHOR_SERVICE, anchor.vault_id)]
        assert set(json.loads(encoded)) == {
            "version",
            "vault_id",
            "generation",
            "key_generation",
            "file_sha256",
        }
        assert FAKE_PASSWORD not in encoded
        backend.records.pop((ANCHOR_SERVICE, anchor.vault_id))
        assert read_encrypted_file(v3_path, FAKE_PASSWORD) == FAKE_PAYLOAD


def test_anchor_disable_changes_file_before_cleanup_error(
    v3_path: Path, backend: MemoryBackend
) -> None:
    with _approved(backend):
        enable_rollback_anchor(v3_path, FAKE_PASSWORD)
        backend.fail_delete = True
        with pytest.raises(DeviceKeyringCleanupRequired, match="enforcement is disabled"):
            disable_rollback_anchor(v3_path, FAKE_PASSWORD)

    parsed = parse_vault_container(v3_path.read_bytes())
    assert isinstance(parsed, V3Container)
    assert ROLLBACK_ANCHOR_EXTENSION not in parsed.header.extensions
    assert decrypt_v3_payload(FAKE_PASSWORD, parsed) == FAKE_PAYLOAD


def test_cli_device_and_anchor_lifecycle_discloses_no_key_material(
    v3_path: Path, backend: MemoryBackend
) -> None:
    runner = CliRunner()
    commands = (
        [
            "v3",
            "device-enable",
            "--vault-path",
            str(v3_path),
            "--password",
            FAKE_PASSWORD,
        ],
        [
            "v3",
            "rollback-anchor",
            "enable",
            "--vault-path",
            str(v3_path),
            "--password",
            FAKE_PASSWORD,
        ],
        ["v3", "rollback-anchor", "inspect", "--vault-path", str(v3_path)],
        [
            "v3",
            "rollback-anchor",
            "verify",
            "--vault-path",
            str(v3_path),
            "--password",
            FAKE_PASSWORD,
        ],
        [
            "v3",
            "rollback-anchor",
            "disable",
            "--vault-path",
            str(v3_path),
            "--password",
            FAKE_PASSWORD,
        ],
        [
            "v3",
            "device-disable",
            "--vault-path",
            str(v3_path),
            "--password",
            FAKE_PASSWORD,
        ],
    )
    outputs: list[str] = []
    with _approved(backend):
        for command in commands:
            result = runner.invoke(main, command)
            assert result.exit_code == 0, result.output
            outputs.append(result.output)

    rendered = "".join(outputs)
    assert FAKE_PASSWORD not in rendered
    assert all(value not in rendered for value in backend.written_values)

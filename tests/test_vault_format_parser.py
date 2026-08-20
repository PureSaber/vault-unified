from __future__ import annotations

import base64
import copy
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from vault_unified.cli import main
from vault_unified.crypto import decrypt_payload, encrypt_payload, write_encrypted_file
from vault_unified.vault_format import (
    V3_MAGIC,
    LegacyContainer,
    UnsupportedVaultVersion,
    V3Container,
    V3ReadOnlyError,
    VaultFormatError,
    VaultKind,
    describe_vault_container,
    inspect_vault_format_file,
    parse_vault_container,
)


FAKE_VAULT_ID = "11111111-1111-4111-8111-111111111111"
FAKE_DEK_ID = "22222222-2222-4222-8222-222222222222"
FAKE_SLOT_ID = "33333333-3333-4333-8333-333333333333"


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _valid_header(ciphertext_length: int = 16) -> dict:
    return {
        "format_version": 3,
        "vault_id": FAKE_VAULT_ID,
        "generation": 1,
        "payload_schema": 2,
        "cipher": "AES-256-GCM",
        "payload_nonce": _b64(b"p" * 12),
        "ciphertext_length": ciphertext_length,
        "dek_id": FAKE_DEK_ID,
        "key_slots": [
            {
                "slot_id": FAKE_SLOT_ID,
                "type": "password",
                "kdf": {
                    "name": "argon2id",
                    "version": 19,
                    "memory_kib": 65_536,
                    "passes": 3,
                    "lanes": 4,
                    "salt": _b64(b"s" * 16),
                    "output_bytes": 32,
                },
                "wrap_cipher": "AES-256-GCM",
                "wrap_nonce": _b64(b"w" * 12),
                "wrapped_dek": _b64(b"d" * 48),
            }
        ],
    }


def _frame(header: dict | None = None, ciphertext: bytes = b"c" * 16) -> bytes:
    value = copy.deepcopy(header if header is not None else _valid_header(len(ciphertext)))
    raw_header = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return V3_MAGIC + len(raw_header).to_bytes(4, "big") + raw_header + ciphertext


def _raw_frame(raw_header: bytes, ciphertext: bytes = b"c" * 16) -> bytes:
    return V3_MAGIC + len(raw_header).to_bytes(4, "big") + raw_header + ciphertext


def test_legacy_bytes_are_classified_without_modification() -> None:
    blob = encrypt_payload("generated-fake-password", {"version": 2, "entries": {}})

    parsed = parse_vault_container(blob)

    assert isinstance(parsed, LegacyContainer)
    assert parsed.kind == VaultKind.LEGACY
    assert parsed.blob == blob
    assert decrypt_payload("generated-fake-password", blob) == {
        "version": 2,
        "entries": {},
    }


def test_valid_v3_frame_is_structurally_parsed_read_only() -> None:
    parsed = parse_vault_container(_frame())

    assert isinstance(parsed, V3Container)
    assert parsed.kind == VaultKind.V3
    assert parsed.header.vault_id == FAKE_VAULT_ID
    assert parsed.header.generation == 1
    assert parsed.header.key_slots[0].kdf.memory_kib == 65_536
    assert parsed.ciphertext == b"c" * 16


def test_v3_decryption_stops_before_legacy_kdf() -> None:
    with patch("vault_unified.crypto.derive_key") as derive:
        with pytest.raises(V3ReadOnlyError, match="5c"):
            decrypt_payload("generated-fake-password", _frame())
    derive.assert_not_called()


def test_legacy_writer_refuses_to_overwrite_v3(tmp_path: Path) -> None:
    path = tmp_path / "fake.vault"
    frame = _frame()
    path.write_bytes(frame)

    with pytest.raises(V3ReadOnlyError, match="Refusing"):
        write_encrypted_file(
            path,
            "generated-fake-password",
            {"version": 2, "entries": {}},
        )
    assert path.read_bytes() == frame


@pytest.mark.parametrize(
    "damaged",
    (
        b"VLTUV4\r\n" + b"\x00" * 20,
        b"VLTUV3\r",
        b"VLTUV",
        b"VLTUVx-not-a-legacy-salt",
    ),
)
def test_unknown_or_truncated_family_prefix_never_falls_back(damaged: bytes) -> None:
    with pytest.raises(UnsupportedVaultVersion):
        parse_vault_container(damaged)


def test_truncated_fixed_prefix_and_header_are_rejected() -> None:
    with pytest.raises(VaultFormatError, match="fixed prefix"):
        parse_vault_container(V3_MAGIC)
    with pytest.raises(VaultFormatError, match="Truncated V3 header"):
        parse_vault_container(V3_MAGIC + (100).to_bytes(4, "big") + b"{}")


def test_declared_ciphertext_length_must_match_exactly() -> None:
    header = _valid_header(ciphertext_length=17)
    with pytest.raises(VaultFormatError, match="does not match"):
        parse_vault_container(_frame(header, b"c" * 16))


def test_duplicate_and_unknown_json_fields_are_rejected() -> None:
    valid = json.dumps(_valid_header(), separators=(",", ":"))
    duplicate = valid.replace(
        '"format_version":3,',
        '"format_version":3,"format_version":3,',
        1,
    ).encode("utf-8")
    with pytest.raises(VaultFormatError, match="Duplicate JSON field"):
        parse_vault_container(_raw_frame(duplicate))

    header = _valid_header()
    header["unexpected"] = True
    with pytest.raises(VaultFormatError, match="Unknown V3 header fields"):
        parse_vault_container(_frame(header))


def test_invalid_utf8_and_noncanonical_base64url_are_rejected() -> None:
    with pytest.raises(VaultFormatError, match="UTF-8"):
        parse_vault_container(_raw_frame(b"\xff\xfe"))

    header = _valid_header()
    header["payload_nonce"] = _b64(b"p" * 12) + "="
    with pytest.raises(VaultFormatError, match="base64url"):
        parse_vault_container(_frame(header))


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("memory_kib", 65_535),
        ("memory_kib", 262_145),
        ("passes", 0),
        ("passes", 7),
        ("lanes", 0),
        ("lanes", 5),
        ("output_bytes", 31),
        ("version", 16),
    ),
)
def test_kdf_resource_downgrades_and_exhaustion_are_rejected(field: str, value: int) -> None:
    header = _valid_header()
    header["key_slots"][0]["kdf"][field] = value
    with pytest.raises(VaultFormatError):
        parse_vault_container(_frame(header))


def test_combined_kdf_work_limit_is_checked_before_crypto() -> None:
    header = _valid_header()
    header["key_slots"][0]["kdf"].update(memory_kib=262_144, passes=4)
    with pytest.raises(VaultFormatError, match="work policy"):
        parse_vault_container(_frame(header))


def test_duplicate_slot_ids_are_rejected() -> None:
    header = _valid_header()
    header["key_slots"].append(copy.deepcopy(header["key_slots"][0]))
    with pytest.raises(VaultFormatError, match="Duplicate key slot"):
        parse_vault_container(_frame(header))


def test_extensions_are_namespaced_bounded_scalars() -> None:
    header = _valid_header()
    header["extensions"] = {"example.org:feature": True}
    parsed = parse_vault_container(_frame(header))
    assert isinstance(parsed, V3Container)
    assert parsed.header.extensions == {"example.org:feature": True}

    header["extensions"] = {"not-namespaced": True}
    with pytest.raises(VaultFormatError, match="namespace-qualified"):
        parse_vault_container(_frame(header))


def test_file_inspection_and_description_are_read_only_and_non_secret(tmp_path: Path) -> None:
    path = tmp_path / "synthetic.vault"
    frame = _frame()
    path.write_bytes(frame)
    before = path.stat()

    description = describe_vault_container(inspect_vault_format_file(path))

    after = path.stat()
    assert path.read_bytes() == frame
    assert after.st_mtime_ns == before.st_mtime_ns
    assert description == {
        "kind": "v3-read-only",
        "container_version": 3,
        "payload_schema": 2,
        "generation": 1,
        "vault_id": FAKE_VAULT_ID,
        "cipher": "AES-256-GCM",
        "key_slot_count": 1,
        "key_slot_types": ["password"],
        "kdf": "argon2id",
    }
    rendered = json.dumps(description)
    assert _b64(b"s" * 16) not in rendered
    assert _b64(b"d" * 48) not in rendered


def test_cli_format_inspect_needs_no_password_and_writes_nothing(tmp_path: Path) -> None:
    path = tmp_path / "synthetic.vault"
    frame = _frame()
    path.write_bytes(frame)

    result = CliRunner().invoke(main, ["format", "inspect", "--vault-path", str(path)])

    assert result.exit_code == 0, result.output
    assert "v3-read-only" in result.output
    assert FAKE_VAULT_ID in result.output
    assert path.read_bytes() == frame


def test_complete_file_limit_is_checked_before_classification(monkeypatch) -> None:
    monkeypatch.setattr("vault_unified.vault_format.MAX_VAULT_BYTES", 64)
    with pytest.raises(VaultFormatError, match="hard limit"):
        parse_vault_container(b"legacy" * 11)

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from vault_unified.adapters.bitwarden import (
    BITWARDEN_LOGIN,
    BITWARDEN_SECURE_NOTE,
    BitwardenAdapter,
)
from vault_unified.models import SecretEntry, Source


def _completed(stdout: str = "", stderr: str = "", code: int = 0):
    return MagicMock(returncode=code, stdout=stdout, stderr=stderr)


def test_login_import_preserves_secondary_uris_totp_and_custom_fields() -> None:
    item = {
        "id": "item-1",
        "type": BITWARDEN_LOGIN,
        "name": "GitHub",
        "notes": "note",
        "revisionDate": "2026-08-21T00:00:00Z",
        "login": {
            "username": "user@example.com",
            "password": "secret",
            "totp": "otpauth://totp/example",
            "uris": [
                {"uri": "https://github.com", "match": 0},
                {"uri": "https://gist.github.com", "match": 1},
            ],
        },
        "fields": [{"name": "pin", "value": "1234", "type": 1}],
        "folderId": "folder-1",
        "favorite": True,
        "reprompt": 1,
    }

    entry = BitwardenAdapter()._item_to_entry(item)

    assert entry is not None
    assert entry.url == "https://github.com"
    metadata = entry.source_metadata[Source.BITWARDEN.value]
    assert metadata["uris"] == item["login"]["uris"]
    assert metadata["totp"] == "otpauth://totp/example"
    assert metadata["fields"] == item["fields"]
    assert metadata["folder_id"] == "folder-1"


def test_update_login_preserves_remote_secondary_fields() -> None:
    adapter = BitwardenAdapter()
    existing = {
        "id": "item-1",
        "type": BITWARDEN_LOGIN,
        "name": "Old",
        "notes": "old note",
        "revisionDate": "old-revision",
        "login": {
            "username": "old-user",
            "password": "old-password",
            "totp": "otpauth://totp/current",
            "uris": [
                {"uri": "https://old.example", "match": 0},
                {"uri": "https://secondary.example", "match": 1},
            ],
        },
        "fields": [{"name": "pin", "value": "1234", "type": 1}],
        "attachments": [{"id": "attachment-1", "fileName": "recovery.txt"}],
    }
    captured: dict = {}

    def fake_bw(args, *, input_text=None):
        if args[:2] == ["get", "item"]:
            return _completed(json.dumps(existing))
        if args[:2] == ["edit", "item"]:
            updated = dict(captured["payload"])
            updated["revisionDate"] = "new-revision"
            return _completed(json.dumps(updated))
        raise AssertionError(args)

    def fake_encode(payload):
        captured["payload"] = payload
        return "encoded"

    entry = SecretEntry(
        title="New",
        username="new-user",
        password="new-password",
        url="https://new.example",
        notes="new note",
        external_id="item-1",
    )
    entry.link_source(Source.BITWARDEN, "item-1")

    with patch.object(adapter, "_bw", side_effect=fake_bw), patch.object(
        adapter, "_encode", side_effect=fake_encode
    ):
        updated = adapter.update_entry(entry)

    payload = captured["payload"]
    assert payload["login"]["uris"][0]["uri"] == "https://new.example"
    assert payload["login"]["uris"][1] == existing["login"]["uris"][1]
    assert payload["login"]["totp"] == existing["login"]["totp"]
    assert payload["fields"] == existing["fields"]
    assert payload["attachments"] == existing["attachments"]
    assert updated.remote_updated_at == "new-revision"


def test_secure_note_round_trip_never_maps_notes_to_password() -> None:
    adapter = BitwardenAdapter()
    remote = {
        "id": "note-1",
        "type": BITWARDEN_SECURE_NOTE,
        "name": "Recovery codes",
        "notes": "one-time codes",
        "secureNote": {"type": 0},
        "revisionDate": "r1",
    }
    entry = adapter._item_to_entry(remote)
    assert entry is not None
    assert entry.password == ""
    assert entry.notes == "one-time codes"

    captured: dict = {}

    def fake_bw(args, *, input_text=None):
        if args[:3] == ["get", "template", "item"]:
            return _completed(json.dumps({"type": 1, "name": "", "login": {}}))
        if args[:2] == ["create", "item"]:
            created = dict(captured["payload"])
            created.update({"id": "note-2", "revisionDate": "r2"})
            return _completed(json.dumps(created))
        raise AssertionError(args)

    def fake_encode(payload):
        captured["payload"] = payload
        return "encoded"

    entry.external_id = ""
    entry.linked_sources = {}
    with patch.object(adapter, "_bw", side_effect=fake_bw), patch.object(
        adapter, "_encode", side_effect=fake_encode
    ):
        created = adapter.create_entry(entry)

    assert captured["payload"]["type"] == BITWARDEN_SECURE_NOTE
    assert "login" not in captured["payload"]
    assert captured["payload"]["notes"] == "one-time codes"
    assert created.password == ""


def test_create_refuses_lossy_attachment_recreation() -> None:
    adapter = BitwardenAdapter()
    entry = SecretEntry(
        title="With attachment",
        source_metadata={
            Source.BITWARDEN.value: {
                "item_type": BITWARDEN_LOGIN,
                "has_attachments": True,
            }
        },
    )

    with patch.object(adapter, "_bw") as bw:
        with pytest.raises(RuntimeError, match="attachments"):
            adapter.create_entry(entry)
    bw.assert_not_called()


def test_source_metadata_round_trips_without_changing_legacy_empty_shape() -> None:
    plain = SecretEntry(title="Plain")
    assert "source_metadata" not in plain.to_dict()

    enriched = SecretEntry(
        title="Enriched",
        source_metadata={Source.BITWARDEN.value: {"item_type": BITWARDEN_LOGIN}},
    )
    restored = SecretEntry.from_dict(enriched.to_dict())
    assert restored.source_metadata == enriched.source_metadata


def test_trashed_item_is_treated_as_deleted() -> None:
    adapter = BitwardenAdapter()
    trashed = {
        "id": "item-in-trash",
        "type": BITWARDEN_LOGIN,
        "name": "Disposable",
        "deletedDate": "2026-08-27T08:37:59Z",
        "login": {
            "username": "generated-user",
            "password": "generated-secret",
        },
    }

    with patch.object(adapter, "_bw", return_value=_completed(json.dumps(trashed))):
        assert adapter.get_entry("item-in-trash") is None

    assert adapter._item_to_entry(trashed) is None

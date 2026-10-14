from __future__ import annotations

import base64
import copy

import pytest

from test_organization import organized_api
from vault_unified.duplicate_merge import MERGE_FIELDS, duplicate_groups, prepare_merge
from vault_unified.manager import UnifiedVault
from vault_unified.models import SecretEntry
from vault_unified.organization import organization_for, prepare_action
from vault_unified.personal_data import (
    MERGED_HISTORY_KEY, add_attachment, all_history, data_for, list_history,
    merge_personal_metadata, record_history, restore_history, set_data, update_data,
)
from vault_unified.v3_crypto import create_v3_file


@pytest.fixture
def merge_api(organized_api):
    client, headers, vault, first, second = organized_api
    vault.local.update(second.id, username=first.username, url=first.url)
    return client, headers, vault, first, second


def body_for(first, second):
    return {"target_id": first.id, "source_id": second.id, "choices": {field: "target" for field in MERGE_FIELDS}}


def preview(client, headers, body):
    result = client.post("/api/organization/merge/preview", headers=headers, json=body)
    assert result.status_code == 200, result.text
    return result.json()


def apply(client, headers, body, plan):
    return client.post("/api/organization/merge/apply", headers=headers, json={**body, "preview_token": plan["preview_token"], "confirm": True})


def test_merge_preserves_selected_fields_all_histories_attachments_and_reopen(merge_api):
    client, headers, vault, first, second = merge_api
    for entry in (first, second):
        update_data(entry, custom_fields=[{"label": "Generated", "value": entry.id, "concealed": True}], totp_secret="GENERATED")
        entry.notes = "generated-note-" + entry.id
        for index in range(20):
            entry.password = f"generated-{entry.id}-{index}"
            record_history(entry)
        add_attachment(entry, filename=entry.id + ".txt", mime_type="text/plain", data_b64=base64.b64encode(entry.id.encode()).decode())
        vault.local.replace_entry(entry)
    original_histories = {item["id"]: item for entry in (first, second) for item in all_history(entry)}
    body = body_for(first, second)
    body["choices"].update(password="source", custom_fields="source", notes="source")
    before = vault.vault_path.read_bytes()
    plan = preview(client, headers, body)
    assert vault.vault_path.read_bytes() == before
    assert plan["history_count"] == 42 and plan["attachment_count"] == 2
    assert "generated-note" not in str(plan)
    assert apply(client, headers, body, plan).status_code == 200
    merged = vault.get(first.id)
    assert merged.title == first.title and merged.password == second.password and merged.notes == second.notes
    assert data_for(merged)["custom_fields"] == data_for(second)["custom_fields"]
    assert len(data_for(merged)["attachments"]) == 2
    assert organization_for(vault.get(second.id))["state"] == "trash"
    assert all(item in all_history(merged) for item in original_histories.values())
    # Rolling edit history cannot age out the versions protected by this merge.
    for index in range(25):
        record_history(merged)
        merged.password = f"generated-after-merge-{index}"
    vault.local.replace_entry(merged)
    reopened = UnifiedVault(vault.vault_path, "generated-only").get(first.id)
    assert set(original_histories) <= {item["id"] for item in all_history(reopened)}
    old_id, old_item = next(iter(original_histories.items()))
    restore_history(reopened, old_id)
    assert reopened.password == old_item["snapshot"]["password"]
    assert all(not item["snapshot"]["password"] and not item["snapshot"]["notes"] for item in list_history(reopened))
    refreshed = merge_personal_metadata(reopened.source_metadata, {"remote": "generated"})
    assert refreshed[MERGED_HISTORY_KEY] == reopened.source_metadata[MERGED_HISTORY_KEY]


def test_cancel_stale_altered_and_replayed_merge_never_write(merge_api):
    client, headers, vault, first, second = merge_api
    body = body_for(first, second)
    original = vault.vault_path.read_bytes()
    plan = preview(client, headers, body)
    assert client.post("/api/organization/merge/apply", headers=headers, json={**body, "preview_token": plan["preview_token"]}).status_code == 400
    assert client.post("/api/organization/merge/cancel", headers=headers, json={"preview_token": plan["preview_token"]}).status_code == 200
    assert apply(client, headers, body, plan).status_code == 409
    assert vault.vault_path.read_bytes() == original
    plan = preview(client, headers, body)
    changed = copy.deepcopy(body)
    changed["choices"]["password"] = "source"
    assert apply(client, headers, changed, plan).status_code == 409
    assert vault.vault_path.read_bytes() == original
    plan = preview(client, headers, body)
    vault.local.update(first.id, notes="Generated concurrent edit")
    before = vault.vault_path.read_bytes()
    assert apply(client, headers, body, plan).status_code == 409
    assert vault.vault_path.read_bytes() == before
    plan = preview(client, headers, body)
    assert apply(client, headers, body, plan).status_code == 200
    once = vault.vault_path.read_bytes()
    assert apply(client, headers, body, plan).status_code == 409
    assert vault.vault_path.read_bytes() == once


def test_failed_atomic_write_keeps_both_original_accounts(merge_api, monkeypatch):
    from vault_unified import local_store
    client, headers, vault, first, second = merge_api
    body = body_for(first, second)
    plan = preview(client, headers, body)
    before, encrypted = vault.local.export_payload(), vault.vault_path.read_bytes()
    def fail(*args, **kwargs):
        raise OSError("Generated atomic write failure")
    monkeypatch.setattr(local_store, "write_encrypted_file", fail)
    assert apply(client, headers, body, plan).status_code == 409
    assert vault.local.export_payload() == before
    assert vault.vault_path.read_bytes() == encrypted


def test_attachment_limit_and_invalid_pairs_fail_before_write(merge_api):
    client, headers, vault, first, second = merge_api
    for entry in (first, second):
        for index in range(6):
            add_attachment(entry, filename=f"{entry.id}-{index}.txt", mime_type="text/plain", data_b64="Z2VuZXJhdGVk")
        vault.local.replace_entry(entry)
    before = vault.vault_path.read_bytes()
    body = body_for(first, second)
    assert client.post("/api/organization/merge/preview", headers=headers, json=body).status_code == 409
    assert vault.vault_path.read_bytes() == before
    body["source_id"] = first.id
    assert client.post("/api/organization/merge/preview", headers=headers, json=body).status_code == 409
    assert vault.vault_path.read_bytes() == before


def test_duplicate_detection_is_exact_and_excludes_nonactive_and_nonlogin():
    first = SecretEntry(title="Generated A", username="User", url="https://example.invalid/login")
    second = SecretEntry(title="Generated B", username="User", url="https://EXAMPLE.invalid/other")
    variants = []
    for changes in ({"username": "user"}, {"username": ""}, {"url": "https://www.example.invalid"}, {"url": "https://example.invalid:8443"}, {"url": "javascript:example.invalid"}):
        entry = SecretEntry(title="Generated variant", username=first.username, url=first.url)
        for field, value in changes.items():
            setattr(entry, field, value)
        variants.append(entry)
    variants += [prepare_action(copy.deepcopy(second), "archive", tags=[]), prepare_action(copy.deepcopy(second), "trash", tags=[])]
    note = SecretEntry(title="Generated note", username=first.username, url=first.url)
    update_data(note, entry_type="secure_note")
    assert duplicate_groups([first, second, note, *variants]) == [[first.id, second.id]]


def test_attachment_id_collision_keeps_both_binaries():
    first = SecretEntry(title="Generated", username="user", url="https://example.invalid")
    second = copy.deepcopy(first)
    second.id = "generated-other-id"
    for entry, encoded in ((first, "Zmlyc3Q="), (second, "c2Vjb25k")):
        add_attachment(entry, filename="generated.txt", mime_type="text/plain", data_b64=encoded)
    other = data_for(second)
    other["attachments"][0]["id"] = data_for(first)["attachments"][0]["id"]
    set_data(second, other)
    merged, _ = prepare_merge(first, second, body_for(first, second)["choices"])
    assert len({item["id"] for item in data_for(merged)["attachments"]}) == 2
    assert {item["data_b64"] for item in data_for(merged)["attachments"]} == {"Zmlyc3Q=", "c2Vjb25k"}


def test_old_payload_refuses_merge_without_modifying_its_file(tmp_path):
    from vault_unified.api.routes.organization import MergeIn, merge_candidates
    path = tmp_path / "old.vault"
    create_v3_file(path, "generated-only", {"version": 2, "entries": {}})
    vault = UnifiedVault(path, "generated-only")
    first = vault.add("Generated A", username="generated", url="https://example.invalid", auto_push=False)
    second = vault.add("Generated B", username="generated", url=first.url, auto_push=False)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="Upgrade"):
        merge_candidates(vault, MergeIn(**body_for(first, second)))
    assert path.read_bytes() == before

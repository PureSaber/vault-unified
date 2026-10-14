from __future__ import annotations

import json
from uuid import uuid4

import pytest

from test_organization import organized_api
from vault_unified.browser_pairing import matches_for_url
from vault_unified.import_flow import inspect_transfer, secure_entry_fingerprint
from vault_unified.manager import UnifiedVault
from vault_unified.personal_data import merge_personal_metadata
from vault_unified.recovery_kit import create_recovery_kit, restore_from_recovery_kit
from vault_unified.template_data import TEMPLATE_KEY, template_for
from vault_unified.transfer import export_transfer, import_entries, parse_transfer, prepare_imported_entry
from vault_unified.v3_crypto import create_v3_file


def codes():
    return {"recovery_codes": [{"id": "generated-code-one", "value": "generated-recovery-one", "used_at": ""}, {"id": "generated-code-two", "value": "generated-recovery-two", "used_at": ""}]}


def create(client, headers, kind="recovery_code", data=None):
    response = client.post("/api/entries", headers=headers, json={"title": "Generated template", "entry_type": kind, "password": "" if kind == "recovery_code" else "generated-template-key", "username": "generated", "url": "https://example.invalid", "template_data": data if data is not None else codes()})
    assert response.status_code == 200, response.text
    return response.json()


def test_recovery_codes_copy_used_tracking_history_and_atomic_failure(organized_api, monkeypatch):
    client, headers, vault, _, _ = organized_api
    entry = create(client, headers)
    copied = []
    monkeypatch.setattr("vault_unified.api.routes.entries.copy_to_clipboard", copied.append)
    before = vault.vault_path.read_bytes()
    assert client.post(f"/api/entries/{entry['id']}/recovery-codes/generated-code-one/copy", headers=headers).status_code == 200
    assert copied == ["generated-recovery-one"]
    assert vault.vault_path.read_bytes() == before
    used = codes()
    used["recovery_codes"][0]["used_at"] = "2026-10-14T12:34:56+00:00"
    response = client.patch(f"/api/entries/{entry['id']}", headers=headers, json={"template_data": used})
    assert response.status_code == 200, response.text
    current = response.json()
    assert client.post(f"/api/entries/{entry['id']}/recovery-codes/generated-code-one/copy", headers=headers).status_code == 409
    history = client.get(f"/api/entries/{entry['id']}/history", headers=headers).json()["history"]
    assert history[0]["snapshot"]["template_data"] == {}
    preview = client.get(f"/api/entries/{entry['id']}/history/{history[0]['id']}", headers=headers).json()["entry"]
    assert preview["template_data"] == codes()
    body = {**current, "entry_id": entry["id"], "transaction_id": str(uuid4()), "expected_updated_at": current["updated_at"], "template_data": preview["template_data"], "restore_history_id": history[0]["id"]}
    assert client.post("/api/entries/commit", headers=headers, json=body).status_code == 200
    assert template_for(UnifiedVault(vault.vault_path, "generated-only").get(entry["id"])) == codes()
    from vault_unified import local_store
    snapshot, encrypted = vault.local.export_payload(), vault.vault_path.read_bytes()
    def fail(*args, **kwargs):
        raise OSError("generated template write failure")
    monkeypatch.setattr(local_store, "write_encrypted_file", fail)
    assert client.patch(f"/api/entries/{entry['id']}", headers=headers, json={"template_data": used}).status_code == 500
    assert vault.local.export_payload() == snapshot and vault.vault_path.read_bytes() == encrypted


def test_license_api_templates_stay_out_of_browser_and_concealed_responses(organized_api):
    client, headers, vault, _, _ = organized_api
    for kind, data in [("software_license", {"registered_to": "Generated owner", "expires_on": "2027-10-14"}), ("api_credential", {"environment": "development", "scopes": "generated:read", "expires_on": "2027-11-15"})]:
        entry = create(client, headers, kind, data)
        assert entry["template_data"] == data
        concealed = client.get(f"/api/entries/{entry['id']}", headers=headers).json()
        assert concealed["password"] == "" and concealed["template_data"] == {}
        assert entry["id"] not in [item["id"] for item in matches_for_url(vault, entry["url"])]
        refreshed = merge_personal_metadata(vault.get(entry["id"]).source_metadata, {"generated": True})
        assert refreshed[TEMPLATE_KEY]["data"] == data
        assert b"generated-template-key" not in vault.vault_path.read_bytes()


def test_template_transfer_roundtrip_fingerprints_and_recovery(organized_api, tmp_path):
    client, headers, vault, _, _ = organized_api
    data = codes()
    data["recovery_codes"][0]["used_at"] = "2026-10-14T12:00:00Z"
    entry = create(client, headers, data=data)
    for format_name in ("json", "csv"):
        content, _, _ = export_transfer(vault, format_name)
        if format_name == "json":
            assert json.loads(content)["version"] == 2
        items = parse_transfer(content, format_name)
        imported = next(item for item in items if item.title == entry["title"])
        assert imported.template_data == data
        assert secure_entry_fingerprint(prepare_imported_entry(imported)) == secure_entry_fingerprint(vault.get(entry["id"]))
        _, rows, _ = inspect_transfer(content, format_name)
        assert not any(row.error for row in rows)
    recovery_key = "VU-RK-" + "generated-template-recovery-" * 3
    kit = create_recovery_kit(vault, recovery_key, tmp_path / "offline")
    target = tmp_path / "restored.vault"
    restore_from_recovery_kit(target, kit, recovery_key, "generated-new-master")
    restored = UnifiedVault(target, "generated-new-master").get(entry["id"])
    assert template_for(restored) == data
    legacy_json = json.dumps({"schema": "vault-unified-transfer", "version": 1, "entries": [{"title": "Generated legacy"}]})
    assert parse_transfer(legacy_json, "json")[0].template_data is None


@pytest.mark.parametrize("data", [
    {"recovery_codes": [{"id": "generated", "value": "generated-secret-value", "used_at": "invalid"}]},
    {"recovery_codes": [{"id": "generated", "value": "generated-secret-value", "used_at": ""}] * 2},
    {"recovery_codes": ["generated-secret-value"]},
    {"expires_on": "generated-secret-value"},
])
def test_invalid_templates_do_not_echo_secret_or_mutate(organized_api, data):
    client, headers, vault, _, _ = organized_api
    before = vault.vault_path.read_bytes()
    result = client.post("/api/entries", headers=headers, json={"title": "Generated", "entry_type": "recovery_code", "template_data": data})
    assert result.status_code == 400
    assert "generated-secret-value" not in result.text
    assert vault.vault_path.read_bytes() == before
    invalid_shape = client.post("/api/entries", headers=headers, json={"title": "Generated", "template_data": "generated-secret-value"})
    assert invalid_shape.status_code == 422 and "generated-secret-value" not in invalid_shape.text


def test_import_templates_into_old_payload_preserves_disk_and_memory(tmp_path):
    path = tmp_path / "old.vault"
    create_v3_file(path, "generated-only", {"version": 2, "entries": {}})
    vault = UnifiedVault(path, "generated-only")
    before = path.read_bytes()
    content = json.dumps({"schema": "vault-unified-transfer", "version": 2, "entries": [{"title": "Generated", "entry_type": "recovery_code", "template_data": codes()}]})
    with pytest.raises(ValueError, match="Upgrade"):
        import_entries(vault, parse_transfer(content, "json"))
    assert path.read_bytes() == before and vault.local.list_entries() == []


def test_older_transfer_updates_keep_absent_template_fields(organized_api):
    client, headers, vault, _, _ = organized_api
    entry = create(client, headers, kind="login", data=codes())
    content = json.dumps({"schema": "vault-unified-transfer", "version": 1, "entries": [{"title": entry["title"], "username": entry["username"], "url": entry["url"], "password": "generated-new-password"}]})
    preview = client.post("/api/transfer/import/preview", headers=headers, json={"content": content, "format": "json", "confirm_plaintext": True})
    assert preview.status_code == 200, preview.text
    result = client.post("/api/transfer/import/apply", headers=headers, json={"preview_token": preview.json()["preview_token"], "decisions": [{"preview_id": "item-1", "action": "update", "target_entry_id": entry["id"]}]})
    assert result.status_code == 200, result.text
    assert vault.get(entry["id"]).password == "generated-new-password"
    assert template_for(vault.get(entry["id"])) == codes()


def test_malformed_csv_template_does_not_hide_other_import_rows():
    content = 'title,password,template_data\nGenerated invalid,generated-key,{invalid\nGenerated valid,generated-key,{}\n'
    _, rows, _ = inspect_transfer(content, "csv")
    assert rows[0].error and "generated-key" not in rows[0].error
    assert not rows[1].error and rows[1].entry.title == "Generated valid"

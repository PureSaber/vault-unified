from __future__ import annotations

import json

import pytest

from test_browser_daily_use import app
from vault_unified.browser_pairing import matches_for_url
from vault_unified.duplicate_merge import MERGE_FIELDS, prepare_merge
from vault_unified.local_store import LocalVault
from vault_unified.manager import UnifiedVault
from vault_unified.models import SecretEntry
from vault_unified.personal_data import list_history, restore_history, merge_personal_metadata
from vault_unified.transfer import export_transfer, parse_transfer, prepare_imported_entry, import_entries
from vault_unified.website_rules import WEBSITE_KEY, base_domain, matches_entry, normalize_rules, rules_for, set_rules, suffixes, website


@pytest.mark.parametrize("saved,target,mode,expected", [
    ("https://example.com", "https://www.example.com", "exact", False),
    ("https://example.com/path", "https://example.com:443/other", "exact", True),
    ("https://example.com", "https://example.com.", "exact", False),
    ("https://bücher.de", "https://xn--bcher-kva.de", "exact", True),
    ("https://example.com", "http://example.com", "base_domain", False),
    ("https://example.com", "https://example.com:8443", "base_domain", False),
    ("https://login.example.co.uk", "https://accounts.example.co.uk", "base_domain", True),
    ("https://example.co.uk", "https://other.co.uk", "base_domain", False),
    ("https://owner.github.io", "https://other.github.io", "base_domain", False),
    ("https://owner.github.io", "https://child.owner.github.io", "base_domain", True),
    ("https://example.com", "https://example.com.evil.com", "base_domain", False),
    ("http://[::1]:8080", "http://[0:0:0:0:0:0:0:1]:8080", "exact", True),
])
def test_matching_respects_explicit_origin_and_public_private_suffix_boundaries(saved, target, mode, expected):
    entry = SecretEntry(title="Generated", url=saved)
    set_rules(entry, {"match": mode})
    assert matches_entry(entry, website(target)) is expected


def test_suffix_lookup_never_fetches_or_uses_disk_cache(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("Website matching must work offline")
    monkeypatch.setattr("requests.sessions.Session.request", fail)
    suffixes.cache_clear()
    assert base_domain("sub.example.co.uk") == "example.co.uk"
    assert base_domain("other.github.io") == "other.github.io"
    assert base_domain("foo.ck") == ""  # PSL wildcard public suffix.
    assert base_domain("www.ck") == "www.ck"  # PSL exception.
    assert not suffixes()._cache.enabled


@pytest.mark.parametrize("url", ["https://name:generated-secret@example.com", "https://example.com\\@evil.com", "https://example.com\n", "javascript:alert(1)", "https://example.com:0", "https://example.com%2eevil.com"])
def test_invalid_website_never_echoes_input(url):
    with pytest.raises(ValueError) as error:
        website(url)
    assert url not in str(error.value)


def test_base_matching_refuses_public_suffixes_ips_and_unknown_domains():
    for url in ("https://co.uk", "https://github.io", "http://127.0.0.1", "http://localhost", "https://example.invalid"):
        with pytest.raises(ValueError):
            set_rules(SecretEntry(title="Generated", url=url), {"match": "base_domain"})
    with pytest.raises(ValueError):
        normalize_rules({"match": []})


def test_browser_fill_totp_exclusion_and_rule_test_share_one_policy(app):
    rule = {"match": "base_domain", "additional_urls": ["https://example.net/login"], "excluded_urls": ["https://blocked.example.com"]}
    response = app.client.post("/api/entries", headers=app.desktop, json={"title": "Generated rule account", "url": "https://login.example.com", "password": "generated-value", "totp_secret": "JBSWY3DPEHPK3PXP", "website_rules": rule})
    assert response.status_code == 200
    entry_id = response.json()["id"]
    before = app.path.read_bytes()
    for target, permitted in (("https://accounts.example.com", True), ("https://example.net", True), ("https://blocked.example.com", False), ("https://example.com.evil.net", False), ("http://example.net", False)):
        checked = app.client.post("/api/entries/tools/website-match", headers=app.desktop, json={"primary_url": "https://login.example.com", "rules": rule, "test_url": target})
        assert checked.json() == {"valid": True, "matches": permitted}
        for route in ("fill", "totp"):
            actual = app.client.post(f"/api/browser/{route}", headers=app.browser, json={"entry_id": entry_id, "url": target})
            assert (actual.status_code == 200) is permitted
    assert app.path.read_bytes() == before
    stored = app.vault.local.get(entry_id)
    assert rules_for(stored)["additional_urls"] == ["https://example.net"]
    from vault_unified.organization import prepare_action
    app.vault.local.replace_entry(prepare_action(stored, "archive", tags=[]))
    assert matches_for_url(app.vault, "https://example.net") == []


def test_rules_survive_history_merge_transfer_remote_metadata_and_failed_save(app, monkeypatch):
    rule = {"additional_urls": ["https://other.example.com"], "excluded_urls": ["https://blocked.example.com"]}
    created = app.client.post("/api/entries", headers=app.desktop, json={"title": "Generated", "username": "generated", "url": "https://example.com", "password": "generated-password", "website_rules": rule}).json()
    entry_id = created["id"]
    changed = app.client.patch(f"/api/entries/{entry_id}", headers=app.desktop, json={"website_rules": {}})
    assert changed.status_code == 200
    entry = app.vault.local.get(entry_id)
    restore_history(entry, list_history(entry)[0]["id"])
    app.vault.local.replace_entry(entry)
    assert rules_for(entry) == normalize_rules(rule)
    assert [item.id for item in app.vault.local.search("other.example.com")] == [entry_id]
    assert merge_personal_metadata(entry.source_metadata, {})[WEBSITE_KEY] == entry.source_metadata[WEBSITE_KEY]
    duplicate = SecretEntry(title="Generated other", username=entry.username, url=entry.url)
    kept, _ = prepare_merge(duplicate, entry, {key: "source" for key in MERGE_FIELDS})
    assert rules_for(kept) == rules_for(entry)
    for format_name in ("json", "csv"):
        content, _, _ = export_transfer(app.vault, format_name)
        restored = prepare_imported_entry(parse_transfer(content, format_name)[0])
        assert rules_for(restored) == rules_for(entry)
    before, payload = app.path.read_bytes(), app.vault.local.export_payload()
    def fail(*args, **kwargs):
        raise OSError("generated failure")
    monkeypatch.setattr("vault_unified.local_store.write_encrypted_file", fail)
    failed = app.client.patch(f"/api/entries/{entry_id}", headers=app.desktop, json={"website_rules": {}})
    assert failed.status_code == 500 and "generated failure" not in failed.text
    assert app.path.read_bytes() == before and app.vault.local.export_payload() == payload


def test_old_imports_preserve_rules_and_old_vault_refuses_new_fields(app, tmp_path):
    created = app.client.post("/api/entries", headers=app.desktop, json={"title": "Generated", "username": "generated", "url": "https://example.com", "password": "generated-old", "website_rules": {"additional_urls": ["https://other.example.com"]}}).json()
    content = json.dumps({"schema": "vault-unified-transfer", "version": 2, "entries": [{"title": "Generated", "username": "generated", "url": "https://example.com", "password": "generated-new"}]})
    preview = app.client.post("/api/transfer/import/preview", headers=app.desktop, json={"content": content, "format": "json", "confirm_plaintext": True})
    assert preview.status_code == 200
    result = app.client.post("/api/transfer/import/apply", headers=app.desktop, json={"preview_token": preview.json()["preview_token"], "decisions": [{"preview_id": "item-1", "action": "update", "target_entry_id": created["id"]}]})
    assert result.status_code == 200
    assert rules_for(app.vault.get(created["id"]))["additional_urls"] == ["https://other.example.com"]
    assert app.vault.get(created["id"]).password == "generated-new"
    old = UnifiedVault.create(tmp_path / "old.vault", "generated-only")
    before = old.vault_path.read_bytes()
    exported, _, _ = export_transfer(app.vault, "json")
    with pytest.raises(ValueError, match="Upgrade"):
        import_entries(old, parse_transfer(exported, "json"))
    assert old.vault_path.read_bytes() == before and old.local.list_entries() == []
    assert LocalVault(app.path, app.master).export_payload() == app.vault.local.export_payload()

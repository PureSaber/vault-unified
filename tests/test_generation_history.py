from __future__ import annotations

import secrets
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from test_browser_daily_use import app
from vault_unified.generator import generate_password, generate_passphrase, passphrase_words
from vault_unified.generation_history import NAMESPACE, MAX_AGE_SECONDS, generate_saved, get_generated, list_generated, retained, origin_hint
from vault_unified.local_store import LocalVault
from vault_unified.session import sessions


def test_passphrase_uses_complete_offline_vocabulary_and_independent_choices(monkeypatch):
    words = passphrase_words()
    assert len(words) == len(set(words)) == 7776
    choices = iter((0, 1, 7775, 0, 3000, 100))
    monkeypatch.setattr("vault_unified.generator.secrets.choice", lambda values: values[next(choices)])
    assert generate_passphrase(separator=" ").split() == [words[index] for index in (0, 1, 7775, 0, 3000, 100)]
    with pytest.raises(ValueError):
        generate_passphrase(5)


def test_character_restrictions_do_not_weaken_enabled_groups_or_loop():
    for _ in range(10):
        value = generate_password(24, symbols=False, excluded="O0Il1")
        assert len(value) == 24 and not set(value) & set("O0Il1")
        assert any(char.isupper() for char in value) and any(char.islower() for char in value) and any(char.isdigit() for char in value)
    assert generate_password(12, upper=False, lower=False, symbols=False).isdigit()
    value = generate_password(20, allowed="abcdefghijABCDEFGHIJ0123456789", symbols=False)
    assert set(value) <= set("abcdefghijABCDEFGHIJ0123456789")
    for options in ({"excluded": "0123456789"}, {"allowed": "aa"}, {"allowed": "with space"}, {"lower": False, "upper": False, "symbols": False, "digits": False}):
        with pytest.raises(ValueError):
            generate_password(**options)


def test_generated_password_is_saved_encrypted_and_retry_is_idempotent(app):
    request_id = str(uuid4())
    body = {"request_id": request_id, "url": "https://example.invalid/private?token=generated-fragment#discard"}
    result = app.client.post("/api/entries/tools/generate", headers=app.desktop, json=body)
    assert result.status_code == 200 and result.headers["cache-control"] == "no-store"
    value = result.json()["password"]
    assert result.json()["history_saved"] and value.encode() not in app.path.read_bytes()
    before = app.path.read_bytes()
    retry = app.client.post("/api/entries/tools/generate", headers=app.desktop, json=body)
    assert retry.json() == result.json() and app.path.read_bytes() == before
    history = app.client.get("/api/entries/tools/generation/history", headers=app.desktop)
    assert value not in history.text and "private" not in history.text and "generated-fragment" not in history.text
    assert history.json()["items"][0]["origin"] == "https://example.invalid"
    copied = []
    # Copy must use only the saved value, not a caller-supplied secret.
    from unittest.mock import patch
    with patch("vault_unified.api.routes.entries.copy_to_clipboard", lambda value, **kwargs: copied.append((value, kwargs))):
        assert app.client.post(f"/api/entries/tools/generation/history/{request_id}/copy", headers=app.desktop).status_code == 200
    assert copied == [(value, {"clear_after": 45})]
    sessions.lock_all()
    assert app.client.get(f"/api/entries/tools/generation/history/{request_id}", headers=app.desktop).status_code == 401
    reopened = LocalVault(app.path, app.master)
    assert get_generated(reopened, request_id)["value"] == value


def test_browser_generation_retained_in_desktop_without_giving_browser_history_access(app):
    result = app.client.post("/api/browser/generate", headers=app.browser, json={"url": "https://example.invalid/sign-up?private=discard"})
    assert result.status_code == 200 and result.json()["history_saved"]
    history = list_generated(app.vault.local)
    assert len(history) == 1 and history[0]["origin"] == "https://example.invalid"
    assert get_generated(app.vault.local, history[0]["id"])["value"] == result.json()["password"]
    assert app.client.get("/api/entries/tools/generation/history", headers=app.browser).status_code != 200


def test_write_failure_preserves_disk_memory_entries_and_generation(app, monkeypatch):
    app.vault.add("Generated retained account", password=secrets.token_urlsafe(16), auto_push=False)
    before, payload, generation = app.path.read_bytes(), app.vault.local.export_payload(), app.vault.local.generation
    def fail(*args, **kwargs):
        raise OSError("generated write failure")
    monkeypatch.setattr("vault_unified.local_store.write_encrypted_file", fail)
    result = app.client.post("/api/entries/tools/generate", headers=app.desktop, json={})
    assert result.status_code == 500 and "generated write failure" not in result.text
    assert app.path.read_bytes() == before and app.vault.local.export_payload() == payload
    assert app.vault.local.generation == generation


def test_retention_count_expiry_and_unlock_cleanup_preserve_other_metadata(app, monkeypatch):
    monkeypatch.setattr("vault_unified.generation_history.time.time", lambda: 2_000_000_000)
    records = [{"id": str(uuid4()), "value": secrets.token_urlsafe(16), "kind": "password", "origin": "", "created_at": 2_000_000_000 - index} for index in range(105)]
    expired = {**records[-1], "id": str(uuid4()), "created_at": 2_000_000_000 - MAX_AGE_SECONDS}
    app.vault.local.update_metadata("vault_unified:other", lambda _: {"keep": True})
    app.vault.local.update_metadata(NAMESPACE, lambda _: {"version": 1, "items": [*records, expired]})
    assert len(list_generated(app.vault.local)) == 100
    with pytest.raises(KeyError):
        get_generated(app.vault.local, expired["id"])
    _, reopened = sessions.unlock(app.master, vault_path=app.path)
    stored = reopened.local.metadata_value(NAMESPACE)["items"]
    assert len(stored) == 100 and not any(item["id"] == expired["id"] for item in stored)
    assert reopened.local.metadata_value("vault_unified:other") == {"keep": True}
    result = generate_saved(reopened.local)
    assert len(list_generated(reopened.local)) == 100 and get_generated(reopened.local, result["history_id"])["value"] == result["password"]


def test_concurrent_generation_keeps_both_records(app):
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: generate_saved(app.vault.local), range(2)))
    assert len(list_generated(app.vault.local)) == 2
    reopened = LocalVault(app.path, app.master)
    for result in results:
        assert get_generated(reopened, result["history_id"])["value"] == result["password"]


def test_old_vault_remains_unchanged_and_unknown_history_is_not_overwritten(tmp_path):
    vault = LocalVault.create(tmp_path / "legacy.vault", secrets.token_urlsafe(24))
    before = vault.vault_path.read_bytes()
    assert generate_saved(vault)["history_saved"] is False and before == vault.vault_path.read_bytes()
    with pytest.raises(ValueError):
        retained({"version": 2, "items": []})
    assert origin_hint("https://generated:password@example.invalid/path") == ""

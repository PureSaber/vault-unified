from __future__ import annotations

import secrets
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from vault_unified.api.app import create_app
from vault_unified.browser_pairing import browser_pairings
from vault_unified.browser_save import browser_saves
from vault_unified.personal_data import list_history
from vault_unified.session import sessions

ORIGIN = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"
OTHER_ORIGIN = "chrome-extension://bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
SITE = "https://example.invalid"


class GeneratedApp(SimpleNamespace):
    def __repr__(self):
        return "<isolated generated browser test>"


@pytest.fixture
def app(tmp_path, monkeypatch):
    path = tmp_path / "generated.vault"
    monkeypatch.setenv("VAULT_FILE", str(path))
    monkeypatch.setenv("VAULT_CONFIG_DIR", str(tmp_path / "config"))
    bootstrap, master = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    sessions.lock_all()
    browser_pairings.clear()
    browser_saves.clear()
    token, vault = sessions.create_v3(master, master, vault_path=path)
    desktop = {"X-Vault-Bootstrap": bootstrap, "Authorization": f"Bearer {token}"}
    with TestClient(create_app(bootstrap_secret=bootstrap)) as client:
        code = client.post("/api/browser/pairing-code", headers=desktop).json()["pairing_code"]
        response = client.post("/api/browser/pair", headers={
            "Origin": ORIGIN, "X-Vault-Browser-Pairing": code,
        }, json={"remember_connection": True})
        assert response.status_code == 200
        paired = response.json()
        yield GeneratedApp(
            client=client, path=path, master=master, bootstrap=bootstrap, token=token,
            vault=vault, desktop=desktop,
            browser={"Origin": ORIGIN, "X-Vault-Browser-Token": paired["browser_token"]},
            connection={"Origin": ORIGIN, "X-Vault-Browser-Connection": paired["connection_key"]},
        )
    sessions.lock_all()
    browser_pairings.clear()
    browser_saves.clear()


def account(**changes):
    return {"entry_id": None, "title": "Generated account", "username": "generated-user",
            "password": secrets.token_urlsafe(24), "url": SITE, **changes}


def preview(app, body):
    result = app.client.post("/api/browser/save/preview", headers=app.browser, json=body)
    assert result.status_code == 200
    assert body["password"] not in result.text
    return result.json()["preview_token"]


def apply(app, body, token, **changes):
    return app.client.post("/api/browser/save/apply", headers=app.browser,
                           json={**body, "preview_token": token, "confirm_save": True, **changes})


def test_save_is_confirmed_atomic_and_retry_does_not_duplicate(app):
    body = account(url=f"{SITE}/signin?private=query#fragment")
    before = app.path.read_bytes()
    token = preview(app, body)
    assert app.path.read_bytes() == before
    assert apply(app, body, token, confirm_save=False).status_code == 400
    assert app.path.read_bytes() == before
    saved = apply(app, body, token)
    assert saved.status_code == 200
    assert body["password"] not in saved.text
    entry = app.vault.get(saved.json()["entry_id"])
    assert entry.password == body["password"]
    assert entry.url == SITE
    after = app.path.read_bytes()
    assert apply(app, body, token).json() == saved.json()
    assert app.path.read_bytes() == after
    assert len(app.vault.list_all()) == 1
    assert app.client.post("/api/browser/save/preview", headers=app.browser, json=body).status_code == 409


def test_update_preserves_history_and_other_fields_and_never_pushes(app, monkeypatch):
    old_password = secrets.token_urlsafe(24)
    entry = app.client.post("/api/entries", headers=app.desktop, json={
        "title": "Existing", "username": "generated-user", "password": old_password,
        "url": SITE + "/login", "notes": "keep this note", "tags": ["keep"],
        "custom_fields": [{"label": "region", "value": "test", "concealed": False}],
    }).json()
    pushes = []
    monkeypatch.setattr(app.vault.sync, "after_local_edit", lambda *args: pushes.append(args))
    body = account(entry_id=entry["id"], title="Updated")
    token = preview(app, body)
    assert apply(app, body, token).status_code == 200
    updated = app.vault.get(entry["id"])
    assert updated.password == body["password"]
    assert updated.notes == "keep this note" and updated.tags == ["keep"]
    assert updated.url == SITE + "/login"
    history = list_history(updated, reveal=True)
    assert history[-1]["snapshot"]["password"] == old_password
    assert history[-1]["snapshot"]["custom_fields"][0]["value"] == "test"
    assert pushes == []


def test_cancel_and_changed_draft_write_nothing(app):
    body = account()
    token = preview(app, body)
    before = app.path.read_bytes()
    assert apply(app, body, token, password=secrets.token_urlsafe(24)).status_code == 409
    assert app.client.post("/api/browser/save/cancel", headers=app.browser,
                           json={"preview_token": token}).status_code == 200
    assert apply(app, body, token).status_code == 409
    assert app.path.read_bytes() == before


def test_stale_preview_does_not_overwrite_desktop_changes(app):
    body = account()
    token = preview(app, body)
    app.vault.add("Concurrent edit", password=secrets.token_urlsafe(20), auto_push=False)
    before = app.path.read_bytes()
    assert apply(app, body, token).status_code == 409
    assert app.path.read_bytes() == before
    assert [entry.title for entry in app.vault.list_all()] == ["Concurrent edit"]


def test_failed_write_has_no_partial_state_and_can_retry(app, monkeypatch):
    body = account()
    token = preview(app, body)
    before = app.path.read_bytes()
    with monkeypatch.context() as patch:
        def fail(*args):
            raise OSError("Generated write failure")
        patch.setattr("vault_unified.local_store.write_encrypted_file", fail)
        failed = apply(app, body, token)
        assert failed.status_code == 500
        assert body["password"] not in failed.text
    assert app.path.read_bytes() == before
    assert app.vault.list_all() == []
    assert apply(app, body, token).status_code == 200


def test_updates_are_scoped_to_the_site_and_login_type(app):
    entry = app.vault.add("Other site", url="https://other.invalid", auto_push=False)
    body = account(entry_id=entry.id)
    assert app.client.post("/api/browser/save/preview", headers=app.browser, json=body).status_code == 400
    note = app.client.post("/api/entries", headers=app.desktop, json={
        "title": "Note", "url": SITE, "entry_type": "secure_note",
    }).json()
    body["entry_id"] = note["id"]
    assert app.client.post("/api/browser/save/preview", headers=app.browser, json=body).status_code == 400


@pytest.mark.parametrize("url", ["http://example.invalid", "https://example.invalid:444", "https://example.invalid.evil.invalid"])
def test_fill_does_not_match_a_different_site(app, url):
    entry = app.vault.add("Login", url=SITE, password=secrets.token_urlsafe(20), auto_push=False)
    assert app.client.post("/api/browser/fill", headers=app.browser,
                           json={"entry_id": entry.id, "url": url}).status_code == 400


def test_browser_tokens_cannot_access_desktop_api_or_other_origins(app):
    body = account()
    wrong = {**app.browser, "Origin": OTHER_ORIGIN}
    assert app.client.post("/api/browser/save/preview", headers=wrong, json=body).status_code == 401
    assert app.client.get("/api/entries", headers=app.browser).status_code == 403
    assert app.client.post("/api/browser/save/preview", headers=app.connection, json=body).status_code == 403
    bad = app.client.post("/api/browser/save/preview", headers=app.browser, json=account(password="x" * 4097))
    assert bad.status_code == 422
    assert "xxxx" not in bad.text


def test_resume_requires_unlock_and_issues_fresh_access_after_lock(app):
    body = account()
    old_preview = preview(app, body)
    assert app.client.post("/api/auth/lock", headers=app.desktop).status_code == 200
    assert app.client.post("/api/browser/status", headers=app.browser).status_code == 401
    assert app.client.post("/api/browser/resume", headers=app.connection).status_code == 423
    unlocked = app.client.post("/api/auth/unlock", headers={"X-Vault-Bootstrap": app.bootstrap},
                               json={"password": app.master}).json()
    resumed = app.client.post("/api/browser/resume", headers=app.connection)
    assert resumed.status_code == 200
    assert resumed.json()["browser_token"] != app.browser["X-Vault-Browser-Token"]
    assert app.client.post("/api/browser/status", headers=app.browser).status_code == 401
    app.browser["X-Vault-Browser-Token"] = resumed.json()["browser_token"]
    assert apply(app, body, old_preview).status_code == 409
    session = sessions._sessions[unlocked["token"]]
    session.last_active -= 30
    before = session.last_active
    assert app.client.post("/api/browser/status", headers=app.browser).status_code == 200
    assert session.last_active == before
    fresh = preview(app, body)
    assert apply(app, body, fresh).status_code == 200


def test_resume_rejects_other_vaults_and_same_path_replacement(app):
    sessions.lock_all()
    sessions.create_v3(app.master, app.master, vault_path=app.path.parent / "other.vault")
    assert app.client.post("/api/browser/resume", headers=app.connection).status_code == 423
    app.path.unlink()
    sessions.create_v3(app.master, app.master, vault_path=app.path)
    assert app.client.post("/api/browser/resume", headers=app.connection).status_code == 423


def test_forget_revokes_connection_even_while_locked(app):
    app.client.post("/api/auth/lock", headers=app.desktop)
    assert app.client.post("/api/browser/disconnect", headers=app.connection).status_code == 200
    sessions.unlock(app.master, vault_path=app.path)
    assert app.client.post("/api/browser/resume", headers=app.connection).status_code == 401


def test_reconnection_is_origin_bound_expires_and_cancel_revokes_it(app, monkeypatch):
    wrong = {**app.connection, "Origin": OTHER_ORIGIN}
    assert app.client.post("/api/browser/resume", headers=wrong).status_code == 401
    app.client.post("/api/browser/disconnect", headers=wrong)
    assert app.client.post("/api/browser/resume", headers=app.connection).status_code == 200
    app.client.post("/api/browser/pairing/cancel", headers=app.desktop)
    assert app.client.post("/api/browser/resume", headers=app.connection).status_code == 401
    code = app.client.post("/api/browser/pairing-code", headers=app.desktop).json()["pairing_code"]
    paired = app.client.post("/api/browser/pair", headers={"Origin": ORIGIN, "X-Vault-Browser-Pairing": code},
                             json={"remember_connection": True}).json()
    import time
    later = time.monotonic() + 43_201
    monkeypatch.setattr("vault_unified.browser_pairing.time.monotonic", lambda: later)
    headers = {"Origin": ORIGIN, "X-Vault-Browser-Connection": paired["connection_key"]}
    assert app.client.post("/api/browser/resume", headers=headers).status_code == 401

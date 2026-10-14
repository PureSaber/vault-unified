import secrets
from uuid import uuid4

import pytest

from test_system_session_lock import runtime
from vault_unified.models import SecretEntry
from vault_unified.organization import ORGANIZATION_KEY
from vault_unified.personal_data import PERSONAL_METADATA_KEY, data_for
from vault_unified.session import sessions


def add_entry(auth, **values):
    vault = sessions.get(auth["Authorization"].split()[1])
    return vault.local.add(SecretEntry(title="Generated application login", username="generated{ENTER}中文", password=secrets.token_hex(20), **values))


def test_native_typing_returns_only_active_login_values_and_never_writes(runtime):
    _, client, headers, auth, _ = runtime
    entry = add_entry(auth)
    vault = sessions.get(auth["Authorization"].split()[1])
    before = vault.vault_path.read_bytes()
    response = client.post("/api/entries/tools/auto-type", headers=auth, json={"entry_id": entry.id})
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json() == {"username": entry.username, "password": entry.password}
    renderer = {key: value for key, value in auth.items() if key != "X-Vault-Native"}
    assert client.post("/api/entries/tools/auto-type", headers=renderer, json={"entry_id": entry.id}).status_code == 403
    assert client.post("/api/entries/tools/auto-type", headers=headers, json={"entry_id": entry.id}).status_code == 401
    assert vault.vault_path.read_bytes() == before
    sessions.lock_all()
    assert client.post("/api/entries/tools/auto-type", headers=auth, json={"entry_id": entry.id}).status_code == 401


@pytest.mark.parametrize("metadata", [
    {ORGANIZATION_KEY: {"state": "archived"}},
    {ORGANIZATION_KEY: {"state": "trash", "trashed_at": "2026-10-14T00:00:00+00:00"}},
    {PERSONAL_METADATA_KEY: {**data_for(SecretEntry(title="Generated")), "entry_type": "secure_note"}},
    {PERSONAL_METADATA_KEY: {"entry_type": "unknown"}},
])
def test_typing_excludes_archived_deleted_and_non_login_items(runtime, metadata):
    _, client, _, auth, _ = runtime
    entry = add_entry(auth, source_metadata=metadata)
    response = client.post("/api/entries/tools/auto-type", headers=auth, json={"entry_id": entry.id})
    assert response.status_code == 400
    assert entry.password not in response.text


def test_typing_rejects_aliases_control_characters_and_missing_items(runtime):
    _, client, _, auth, _ = runtime
    entry = add_entry(auth)
    for entry_id, status in [(entry.title, 422), (str(uuid4()), 400)]:
        assert client.post("/api/entries/tools/auto-type", headers=auth, json={"entry_id": entry_id}).status_code == status
    vault = sessions.get(auth["Authorization"].split()[1])
    for password in ["generated\nsubmit", "generated\tfield", "x" * 257]:
        vault.local.update(entry.id, password=password)
        response = client.post("/api/entries/tools/auto-type", headers=auth, json={"entry_id": entry.id})
        assert response.status_code == 400
        assert password not in response.text

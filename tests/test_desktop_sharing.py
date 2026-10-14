import copy
import json
import secrets
import sqlite3
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from test_system_session_lock import runtime
from vault_unified.api.routes.sharing import Options
from vault_unified.local_store import LocalVault
from vault_unified.models import SecretEntry
from vault_unified.session import sessions
from vault_unified.sharing.client import RemoteError, approve_proposal, verify_family, verify_join_request
from vault_unified.sharing.desktop import DesktopSharing, NAMESPACE, invitation, sharing, state_for
from vault_unified.sharing.protocol import SharingError, canonical, decrypt, encode, encrypt, member_id, new_identity, public_identity, signed_request
from vault_unified.sharing.service import create_app
from vault_unified.sharing.store import Store


@pytest.fixture
def connected(runtime, tmp_path, monkeypatch):
    _, client, _, auth, _ = runtime
    admin = secrets.token_urlsafe(32)
    service = create_app(database=tmp_path / "service" / "generated.db", admin_token=admin)
    credentials, calls, behavior = {}, [], {"before": None, "after": None}
    class Backend:
        def get_password(self, service, account): return credentials.get((service, account))
        def set_password(self, service, account, value): credentials[(service, account)] = value
        def delete_password(self, service, account): credentials.pop((service, account), None)
    with TestClient(service) as remote_client:
        class Bridge:
            def __init__(self, url, identity, *, admin="", check=lambda: None): self.identity, self.admin, self.check = identity, admin, check
            def post(self, path, payload, *, creation=False):
                self.check(); calls.append(path)
                if behavior["before"]: behavior["before"](path)
                response = remote_client.post(path, json=signed_request(self.identity, path, payload), headers={"Authorization": "Bearer " + self.admin} if creation else {})
                if response.status_code != 200: raise RemoteError(response.status_code)
                if behavior["after"]: behavior["after"](path)
                self.check(); return response.json()
        monkeypatch.setattr(sharing, "backend_factory", Backend)
        monkeypatch.setattr(sharing, "remote_factory", Bridge)
        result = client.put("/api/sharing/connection", headers=auth, json={"server": "https://sharing.example.invalid", "admin_token": admin, "confirm": True})
        assert result.status_code == 200
        yield runtime, remote_client, service.state.store, behavior, calls, credentials


def token(auth): return auth["Authorization"].split()[1]


def preview(client, auth, **options):
    value = client.post("/api/sharing/preview", headers=auth, json={"options": options})
    assert value.status_code == 200
    return value.json()["preview_token"]


def apply(client, auth, **options):
    intent = preview(client, auth, **options)
    return client.post("/api/sharing/apply", headers=auth, json={"options": options, "preview_token": intent, "confirm": True})


def personal(runtime):
    vault = sessions.get(token(runtime[3]))
    entry = SecretEntry(title="Generated personal account", username="generated", password=secrets.token_urlsafe(30), url="https://example.invalid", notes=secrets.token_urlsafe(24))
    vault.local.add(entry)
    return vault, entry


def family(connected):
    runtime = connected[0]; client, auth = runtime[1], runtime[3]
    assert apply(client, auth, action="create-family", name="Generated family").status_code == 200
    return client.get("/api/sharing/status", headers=auth).json()["families"][0]["id"]


def invite_member(connected, tmp_path, gid, *, role="reader"):
    runtime = connected[0]; client, auth = runtime[1], runtime[3]
    created = apply(client, auth, action="invite", family_id=gid, role=role)
    assert created.status_code == 200
    code = created.json()["invitation"]
    master = secrets.token_urlsafe(24)
    second, vault = sessions.create_v3(master, master, vault_path=tmp_path / (uuid4().hex + ".vault"))
    second_auth = {**auth, "Authorization": "Bearer " + second}
    assert apply(client, second_auth, action="join-family", invite=code).status_code == 200
    assert client.post(f"/api/sharing/families/{gid}/refresh", headers=second_auth).json()["pending"]
    requests = client.get(f"/api/sharing/families/{gid}/pending", headers=auth).json()["requests"]
    assert len(requests) == 1 and "proof" not in requests[0]
    request = requests[0]
    assert apply(client, auth, action="approve-member", family_id=gid, pending_id=request["id"], member_id=request["identity"], role=role).status_code == 200
    assert client.post(f"/api/sharing/families/{gid}/refresh", headers=second_auth).status_code == 200
    return second_auth, vault, master


def test_cancel_stale_preview_and_field_selection_do_not_leak_personal_data(connected):
    runtime, remote, store, _, calls, credentials = connected
    client, auth = runtime[1], runtime[3]; vault, entry = personal(runtime)
    original = vault.vault_path.read_bytes(); before = len(calls)
    options = {"action": "share", "entry_id": entry.id, "fields": ["username", "password"], "hours": 1, "max_reads": 1}
    intent = preview(client, auth, **options)
    assert client.post("/api/sharing/cancel", headers=auth, json={"preview_token": intent}).status_code == 200
    assert vault.vault_path.read_bytes() == original and len(calls) == before
    assert client.post("/api/sharing/apply", headers=auth, json={"options": options, "preview_token": intent, "confirm": True}).status_code == 409
    intent = preview(client, auth, **options)
    vault.local.add(SecretEntry(title="Another generated item"))
    assert client.post("/api/sharing/apply", headers=auth, json={"options": options, "preview_token": intent, "confirm": True}).status_code == 409
    assert apply(client, auth, **options).status_code == 200
    public = client.get("/api/sharing/status", headers=auth)
    state = state_for(vault.local); item = next(iter(state["shares"].values()))
    assert entry.password not in public.text and entry.notes not in public.text and item["key"] not in public.text
    assert state["identity"]["signing_private"] not in public.text
    assert entry.password.encode() not in store.path.read_bytes() and entry.password.encode() not in vault.vault_path.read_bytes()
    assert all(value not in canonical(vault.local.export_payload()).decode() for value in credentials.values())
    sid = next(iter(state["shares"]))
    link = client.post(f"/api/sharing/shares/{sid}/link", headers=auth, json={"confirm": True}).json()["link"]
    assert item["key"] in link and item["payload"]["capability"] in link
    assert apply(client, auth, action="revoke-share", entry_id=sid).status_code == 200
    assert remote.post(f"/v1/shares/{sid}/read", json={"capability": item["payload"]["capability"]}).status_code == 410


def test_lost_create_response_and_restart_retry_are_idempotent(connected):
    runtime, _, store, behavior, _, _ = connected
    client, auth = runtime[1], runtime[3]; vault, entry = personal(runtime)
    def lost(path):
        if path == "/v1/shares": raise RemoteError(503)
    behavior["after"] = lost
    assert apply(client, auth, action="share", entry_id=entry.id, fields=["password"]).status_code == 400
    state = state_for(vault.local); oid = next(iter(state["outbox"]))
    reopened = LocalVault(vault.vault_path, runtime[4])
    assert state_for(reopened)["outbox"] == state["outbox"]
    behavior["after"] = None
    assert client.post(f"/api/sharing/pending/{oid}/retry", headers=auth, json={"confirm": True}).status_code == 200
    assert state_for(vault.local)["outbox"] == {}
    with store.connect() as db: assert db.execute("SELECT COUNT(*) FROM shares").fetchone()[0] == 1


def test_cancel_pending_upload_records_remote_revocation_before_retry(connected):
    runtime, remote, _, behavior, _, _ = connected
    client, auth = runtime[1], runtime[3]; vault, entry = personal(runtime)
    behavior["before"] = lambda _path: (_ for _ in ()).throw(RemoteError(503))
    assert apply(client, auth, action="share", entry_id=entry.id, fields=["password"]).status_code == 400
    state = state_for(vault.local); sid = next(iter(state["shares"])); old_op = copy.deepcopy(next(iter(state["outbox"].values())))
    behavior["before"] = None
    assert apply(client, auth, action="revoke-share", entry_id=sid).status_code == 200
    reply = sharing.remote_factory(old_op["server"], state["identity"], admin=sharing.admin(vault.local, old_op["server"])).post(old_op["path"], old_op["payload"], creation=True)
    assert reply["revoked"] == 1
    assert remote.post(f"/v1/shares/{sid}/read", json={"capability": old_op["payload"]["capability"]}).status_code == 410


def test_two_independent_profiles_family_permissions_history_and_removal(connected, tmp_path):
    runtime = connected[0]; client, auth = runtime[1], runtime[3]
    vault, original_personal = personal(runtime); gid = family(connected)
    second_auth, second_vault, master = invite_member(connected, tmp_path, gid)
    values = {"title": "Generated shared account", "username": "member", "password": secrets.token_urlsafe(30), "url": "https://example.invalid", "notes": "Generated family note"}
    assert apply(client, auth, action="save-entry", family_id=gid, values=values).status_code == 200
    assert client.post(f"/api/sharing/families/{gid}/refresh", headers=second_auth).status_code == 200
    view = client.get(f"/api/sharing/families/{gid}", headers=second_auth).json(); eid = view["entries"][0]["id"]
    assert view["role"] == "reader" and values["password"] not in json.dumps(view)
    assert client.post("/api/sharing/preview", headers=second_auth, json={"options": {"action": "save-entry", "family_id": gid, "entry_id": eid, "values": values}}).status_code == 400
    assert client.post(f"/api/sharing/families/{gid}/entry/{eid}", headers=second_auth, json={"confirm": True}).json()["password"] == values["password"]
    changed = {**values, "password": secrets.token_urlsafe(30)}
    assert apply(client, auth, action="save-entry", family_id=gid, entry_id=eid, values=changed).status_code == 200
    assert apply(client, auth, action="restore-history", family_id=gid, entry_id=eid, history_index=0).status_code == 200
    assert client.post(f"/api/sharing/families/{gid}/entry/{eid}", headers=auth, json={"confirm": True}).json()["password"] == values["password"]
    assert apply(client, auth, action="trash-entry", family_id=gid, entry_id=eid).status_code == 200
    assert apply(client, auth, action="restore-entry", family_id=gid, entry_id=eid).status_code == 200
    assert len(vault.local.list_entries()) == 1 and vault.local.get(original_personal.id).password == original_personal.password
    assert second_vault.local.list_entries() == []
    member = member_id(public_identity(state_for(second_vault.local)["identity"])["signing_key"])
    assert apply(client, auth, action="remove-member", family_id=gid, member_id=member).status_code == 200
    assert client.post(f"/api/sharing/families/{gid}/refresh", headers=second_auth).status_code == 400
    assert state_for(second_vault.local)["families"][gid]["wire"] is None
    restored = LocalVault(second_vault.vault_path, master)
    assert state_for(restored)["families"][gid]["removed"] is True


def test_lost_write_response_recovers_without_duplicate_history(connected):
    runtime, _, _, behavior, _, _ = connected; client, auth = runtime[1], runtime[3]
    gid = family(connected)
    behavior["after"] = lambda path: (_ for _ in ()).throw(RemoteError(503)) if path.endswith("/write") else None
    values = {"title": "Generated", "username": "", "password": secrets.token_urlsafe(30), "url": "", "notes": ""}
    assert apply(client, auth, action="save-entry", family_id=gid, values=values).status_code == 400
    oid = client.get("/api/sharing/status", headers=auth).json()["outbox"][0]["id"]
    behavior["after"] = None
    assert client.post(f"/api/sharing/pending/{oid}/retry", headers=auth, json={"confirm": True}).status_code == 200
    view = client.get(f"/api/sharing/families/{gid}", headers=auth).json()
    assert len(view["entries"]) == 1 and view["entries"][0]["history_count"] == 0


def test_concurrent_family_edit_preserves_proposal_until_reviewed(connected, tmp_path):
    runtime = connected[0]; client, auth = runtime[1], runtime[3]; gid = family(connected)
    editor_auth, _, _ = invite_member(connected, tmp_path, gid, role="editor")
    values = {"title": "Owner edit", "username": "", "password": secrets.token_urlsafe(30), "url": "", "notes": ""}
    assert apply(client, auth, action="save-entry", family_id=gid, values=values).status_code == 200
    assert apply(client, editor_auth, action="save-entry", family_id=gid, values={**values, "title": "Concurrent edit"}).status_code == 409
    pending = client.get("/api/sharing/status", headers=editor_auth).json()["outbox"]
    assert len(pending) == 1
    assert client.post(f"/api/sharing/pending/{pending[0]['id']}/discard", headers=editor_auth, json={"confirm": True}).status_code == 200
    view = client.get(f"/api/sharing/families/{gid}", headers=editor_auth).json()
    assert [entry["title"] for entry in view["entries"]] == ["Owner edit"]


def test_pending_draft_survives_restart_and_can_be_reviewed_against_latest(connected, tmp_path):
    runtime = connected[0]; client, auth = runtime[1], runtime[3]; gid = family(connected)
    editor_auth, editor, password = invite_member(connected, tmp_path, gid, role="editor")
    values = {"title": "Generated conflict", "username": "owner", "password": secrets.token_urlsafe(30), "url": "", "notes": ""}
    assert apply(client, auth, action="save-entry", family_id=gid, values=values).status_code == 200
    assert client.post(f"/api/sharing/families/{gid}/refresh", headers=editor_auth).status_code == 200
    eid = client.get(f"/api/sharing/families/{gid}", headers=auth).json()["entries"][0]["id"]
    assert apply(client, auth, action="save-entry", family_id=gid, entry_id=eid, values={**values, "username": "new-owner"}).status_code == 200
    proposed = {**values, "password": secrets.token_urlsafe(30)}
    assert apply(client, editor_auth, action="save-entry", family_id=gid, entry_id=eid, values=proposed).status_code == 409
    oid = next(iter(state_for(LocalVault(editor.vault_path, password))["outbox"]))
    review = client.post(f"/api/sharing/pending/{oid}/review", headers=editor_auth, json={"confirm": True})
    assert review.status_code == 200
    options = review.json()["options"]
    assert options["values"] == proposed and review.json()["current"]["username"] == "new-owner"
    intent = preview(client, editor_auth, **options)
    assert client.post("/api/sharing/cancel", headers=editor_auth, json={"preview_token": intent}).status_code == 200
    assert oid in state_for(editor.local)["outbox"]
    options["values"]["username"] = review.json()["current"]["username"]
    assert apply(client, editor_auth, **options).status_code == 200
    assert state_for(editor.local)["outbox"] == {}
    restored = client.post(f"/api/sharing/families/{gid}/entry/{eid}", headers=editor_auth, json={"confirm": True}).json()
    assert restored["username"] == "new-owner" and restored["password"] == proposed["password"]


def test_no_remote_side_effect_when_local_queue_cannot_commit(connected, monkeypatch):
    runtime, _, _, _, calls, _ = connected; client, auth = runtime[1], runtime[3]; vault, entry = personal(runtime)
    before = len(calls); original = vault.vault_path.read_bytes()
    def failed(_payload): raise OSError("generated write failure")
    monkeypatch.setattr(vault.local, "_write_payload", failed)
    assert apply(client, auth, action="share", entry_id=entry.id, fields=["password"]).status_code == 400
    assert len(calls) == before and vault.vault_path.read_bytes() == original and state_for(vault.local)["shares"] == {}


def test_lock_during_remote_response_keeps_encrypted_pending_work(connected):
    runtime, _, _, behavior, _, _ = connected; client, auth = runtime[1], runtime[3]; vault, entry = personal(runtime)
    behavior["after"] = lambda _path: sessions.lock(token(auth))
    assert apply(client, auth, action="share", entry_id=entry.id, fields=["password"]).status_code == 401
    assert len(state_for(LocalVault(vault.vault_path, runtime[4]))["outbox"]) == 1


def test_owner_checks_signed_invitee_encryption_key_not_just_service_response(connected):
    runtime = connected[0]; client, auth = runtime[1], runtime[3]; gid = family(connected)
    code = apply(client, auth, action="invite", family_id=gid).json()["invitation"]; decoded = invitation(code)
    who = new_identity(); public = public_identity(who)
    path = f"/v1/families/{gid}/accept"
    proof = signed_request(who, path, {"id": decoded["id"], "secret": decoded["secret"], "encryption_key": public["encryption_key"]})
    assert connected[1].post(path, json=proof).status_code == 200
    pending = sharing.pending_members(token(auth), gid, internal=True)["requests"][0]
    verify_join_request(pending, gid)
    pending["public"]["encryption_key"] = public_identity(new_identity())["encryption_key"]
    with pytest.raises(SharingError): verify_join_request(pending, gid)
    with pytest.raises(SharingError): verify_join_request({**pending, "public": public}, uuid4().hex)


def test_strict_confirmation_and_preview_binding_block_unapproved_writes(connected):
    runtime, _, _, _, calls, _ = connected
    client, auth = runtime[1], runtime[3]; vault, entry = personal(runtime)
    options = {"action": "share", "entry_id": entry.id, "fields": ["password"]}
    intent = preview(client, auth, **options)
    original, count = vault.vault_path.read_bytes(), len(calls)
    for confirm in (False, "true", 1):
        response = client.post("/api/sharing/apply", headers=auth, json={"options": options, "preview_token": intent, "confirm": confirm})
        assert response.status_code in (400, 422)
    assert client.post("/api/sharing/apply", headers=auth, json={"options": {**options, "fields": ["password", "notes"]}, "preview_token": intent, "confirm": True}).status_code == 400
    assert vault.vault_path.read_bytes() == original and len(calls) == count
    intent = preview(client, auth, **options)
    assert client.post("/api/auth/lock", headers=auth).status_code == 200
    assert client.post("/api/sharing/apply", headers=auth, json={"options": options, "preview_token": intent, "confirm": True}).status_code == 401
    assert len(calls) == count


def test_personal_sync_conflict_display_never_reveals_sharing_keys(tmp_path):
    from test_personal_sync_connections import GeneratedKeyring, profile, connect
    a, am = profile(tmp_path / "a", GeneratedKeyring()); b, bm = profile(tmp_path / "b", GeneratedKeyring())
    original = new_identity()
    a.update_metadata(NAMESPACE, lambda _: {"identity": original})
    connect(a, am, tmp_path); am.synchronize(a)
    connect(b, bm, tmp_path, code=am.code(a)); bm.synchronize(b); am.synchronize(a)
    identities = [new_identity(), new_identity()]
    for local, who in zip((a, b), identities): local.update_metadata(NAMESPACE, lambda _, who=who: {"identity": who})
    am.synchronize(a); bm.synchronize(b); am.synchronize(a)
    for manager, local in ((am, a), (bm, b)):
        result = manager.conflicts(local, reveal=True)
        assert result["items"]
        serialized = json.dumps(result)
        assert all(secret not in serialized for who in [original, *identities] for secret in who.values() if isinstance(secret, str))
        assert all(item["local"]["value"] == "••••••••" and item["remote"]["value"] == "••••••••" for item in result["items"])


def test_service_v1_upgrade_preserves_existing_ciphertext(tmp_path):
    path = tmp_path / "old.db"
    clock = 2000000000; store = Store(path, clock=lambda: clock)
    who, sid, key, cap = new_identity(), uuid4().hex, secrets.token_bytes(32), encode(secrets.token_bytes(32))
    content = {"generated": secrets.token_hex(24)}
    blob = encrypt(key, content, sid)
    store.share_create(signed_request(who, "/v1/shares", {"id": sid, "capability": cap, "blob": blob, "expires": clock + 600, "max_reads": 2}, now=clock), "/v1/shares")
    with sqlite3.connect(path) as db:
        db.executescript("ALTER TABLE pending DROP COLUMN proof; PRAGMA user_version=1;")
        db.execute("INSERT INTO pending VALUES(?,?,?,?,?,?)", (uuid4().hex, uuid4().hex, "generated", "{}", "reader", 2000000000))
    store = Store(path, clock=lambda: clock)
    with store.connect() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM pending").fetchone()[0] == 0
        assert "proof" in [row[1] for row in db.execute("PRAGMA table_info(pending)")]
    assert decrypt(key, store.share_read(sid, {"capability": cap})["blob"], sid) == content

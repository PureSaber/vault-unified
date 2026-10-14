import copy
import json
import secrets
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from vault_unified.sharing.protocol import (SharingError, decode, decrypt, encode, encrypt, member_id, new_identity,
    public_identity, service_url, sign, signed_request, unwrap_key, validate_manifest, verify, wrap_key)
from vault_unified.sharing.service import create_app
from vault_unified.sharing.store import Store, content_value


@pytest.fixture
def service(tmp_path):
    now = [2000000000]
    admin = secrets.token_urlsafe(32)
    app = create_app(database=tmp_path / "sharing.db", admin_token=admin, clock=lambda: now[0])
    with TestClient(app) as client:
        yield client, app.state.store, admin, now


def post(service, identity, path, payload, *, admin=False):
    client, _, token, now = service
    return client.post(path, json=signed_request(identity, path, payload, now=now[0]), headers={"Authorization": "Bearer " + token} if admin else {})


def create_share(service, *, count=1):
    identity, sid, key, cap = new_identity(), uuid4().hex, secrets.token_bytes(32), encode(secrets.token_bytes(32))
    password = secrets.token_urlsafe(30)
    plain = {"version": 1, "id": sid, "title": "Generated item", "expires": service[3][0] + 600, "fields": {"password": password}}
    payload = {"id": sid, "capability": cap, "blob": encrypt(key, plain, "vault-unified:share:v1:" + sid), "expires": plain["expires"], "max_reads": count}
    assert post(service, identity, "/v1/shares", payload, admin=True).status_code == 200
    return identity, sid, key, cap, payload, password


def family_data(identity, gid=None):
    gid, key = gid or uuid4().hex, secrets.token_bytes(32)
    public = public_identity(identity); mid = member_id(public["signing_key"])
    manifest = {"version": 1, "group": gid, "epoch": 1, "members": {mid: {**public, "role": "owner", "wrapped_key": wrap_key(public["encryption_key"], key, f"{gid}:1:{mid}")}}}
    blob = encrypt(key, {"version": 1, "name": "Generated family", "entries": {}}, f"vault-unified:family:v1:{gid}:1")
    payload = {"id": gid, "manifest": manifest, "manifest_signature": sign(identity, manifest), "blob": blob,
               "content_signature": sign(identity, content_value(gid, 1, 1, blob))}
    return gid, key, payload


def create_family(service):
    owner = new_identity(); gid, key, payload = family_data(owner)
    assert post(service, owner, "/v1/families", payload, admin=True).status_code == 200
    return owner, gid, key, payload


def join(service, owner, gid, key, invitee, role="reader"):
    path = f"/v1/families/{gid}"
    iid, secret = uuid4().hex, encode(secrets.token_bytes(32))
    invite = {"id": iid, "secret": secret, "role": role, "expires": service[3][0] + 600}
    assert post(service, owner, path + "/invite", invite).status_code == 200
    public = public_identity(invitee)
    accepted = post(service, invitee, path + "/accept", {"id": iid, "secret": secret, "encryption_key": public["encryption_key"]})
    assert accepted.status_code == 200 and accepted.json()["pending"]
    assert post(service, invitee, path + "/read", {}).status_code == 403
    request = post(service, owner, path + "/pending", {}).json()["requests"][0]
    current = post(service, owner, path + "/read", {}).json()
    mid = member_id(public["signing_key"]); manifest = current["manifest"]
    manifest["members"][mid] = {**public, "role": role, "wrapped_key": wrap_key(public["encryption_key"], key, f"{gid}:{manifest['epoch']}:{mid}")}
    payload = {"revision": current["revision"], "manifest": manifest, "manifest_signature": sign(owner, manifest), "pending_id": request["id"]}
    assert post(service, owner, path + "/approve", payload).status_code == 200
    return mid, payload, invite


def test_single_share_ciphertext_expiry_count_and_revocation(service):
    client, store, _, now = service
    owner, sid, key, cap, payload, password = create_share(service, count=2)
    response = client.post(f"/v1/shares/{sid}/read", json={"capability": cap})
    assert response.status_code == 200 and response.json()["remaining_reads"] == 1
    assert password not in response.text
    assert decrypt(key, response.json()["blob"], "vault-unified:share:v1:" + sid)["fields"]["password"] == password
    assert client.post(f"/v1/shares/{sid}/read", json={"capability": encode(secrets.token_bytes(32))}).status_code == 410
    assert post(service, new_identity(), f"/v1/shares/{sid}/revoke", {}).status_code == 404
    assert post(service, owner, f"/v1/shares/{sid}/revoke", {}).json()["revoked"] == 1
    assert client.post(f"/v1/shares/{sid}/read", json={"capability": cap}).status_code == 410
    assert post(service, owner, "/v1/shares", payload, admin=True).json()["revoked"] == 1
    # Neither request retry nor process restart revives revoked data.
    reopened = Store(store.path, clock=lambda: now[0])
    with reopened.connect() as db:
        assert db.execute("SELECT blob FROM shares WHERE id=?", (sid,)).fetchone()[0] == ""
    _, expired, _, expired_cap, _, _ = create_share(service)
    now[0] += 601
    assert client.post(f"/v1/shares/{expired}/read", json={"capability": expired_cap}).status_code == 410
    assert password.encode() not in store.path.read_bytes()


def test_simultaneous_last_read_is_atomic_and_survives_restart(service):
    client, store, _, now = service
    _, sid, _, cap, _, _ = create_share(service)
    with ThreadPoolExecutor(max_workers=8) as pool:
        statuses = list(pool.map(lambda _: client.post(f"/v1/shares/{sid}/read", json={"capability": cap}).status_code, range(8)))
    assert statuses.count(200) == 1 and statuses.count(410) == 7
    with create_app(database=store.path, admin_token=service[2], clock=lambda: now[0]).state.store.connect() as db:
        row = db.execute("SELECT reads,blob FROM shares WHERE id=?", (sid,)).fetchone()
        assert row[0] == 1 and row[1] == ""


def test_revocation_before_delayed_create_cannot_resurrect_share(service):
    identity, sid = new_identity(), uuid4().hex
    payload = {"id": sid, "capability": encode(secrets.token_bytes(32)), "blob": encrypt(secrets.token_bytes(32), {}, "generated"),
               "expires": service[3][0] + 600, "max_reads": 1}
    assert post(service, identity, f"/v1/shares/{sid}/revoke", {}).status_code == 404
    assert post(service, identity, f"/v1/shares/{sid}/revoke", {}, admin=True).json()["revoked"] == 1
    assert post(service, identity, "/v1/shares", payload, admin=True).json()["revoked"] == 1
    assert service[0].post(f"/v1/shares/{sid}/read", json={"capability": payload["capability"]}).status_code == 410


def test_signed_creation_requires_admin_binds_path_body_and_rejects_replay(service):
    client, _, token, now = service
    identity, sid, _, _, payload, _ = create_share(service)
    assert post(service, identity, "/v1/shares", payload).status_code == 401
    path = f"/v1/shares/{sid}/status"
    request = signed_request(identity, path, {}, now=now[0])
    assert client.post(path, json=request).status_code == 200
    assert client.post(path, json=request).status_code == 409
    assert client.post(path.replace("status", "revoke"), json=request).status_code == 400
    request = signed_request(identity, path, {}, now=now[0])
    request["payload"]["injected"] = token
    response = client.post(path, json=request)
    assert response.status_code == 400 and token not in response.text
    request = signed_request(identity, path, {}, now=now[0] - 61)
    assert client.post(path, json=request).status_code == 400
    assert post(service, identity, "/v1/shares", {**payload, "max_reads": 2}, admin=True).status_code == 409


def test_reader_editor_invitation_and_atomic_concurrent_write(service):
    owner, gid, key, initial = create_family(service); path = f"/v1/families/{gid}"
    reader, editor = new_identity(), new_identity()
    reader_id, _, _ = join(service, owner, gid, key, reader)
    join(service, owner, gid, key, editor, "editor")
    current = post(service, reader, path + "/read", {}).json()
    assert unwrap_key(reader, current["manifest"]["members"][reader_id]["wrapped_key"], f"{gid}:1:{reader_id}") == key
    validate_manifest(current["manifest"], current["owner"], current["manifest_signature"], gid)
    blob = encrypt(key, {"version": 1, "name": "Updated family", "entries": {}}, f"vault-unified:family:v1:{gid}:1")
    payload = {"revision": current["revision"], "epoch": 1, "blob": blob,
               "content_signature": sign(reader, content_value(gid, 1, current["revision"] + 1, blob))}
    assert post(service, reader, path + "/write", payload).status_code == 403
    assert post(service, reader, path + "/pending", {}).status_code == 403
    payload["content_signature"] = sign(editor, content_value(gid, 1, current["revision"] + 1, blob))
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(lambda _: post(service, editor, path + "/write", payload).status_code, range(2)))
    assert sorted(statuses) == [200, 409]
    updated = post(service, owner, path + "/read", {}).json()
    verify(public_identity(editor)["signing_key"], content_value(gid, 1, updated["content_revision"], updated["blob"]), updated["content_signature"])


def test_removal_rotates_every_envelope_and_revokes_future_access(service):
    owner, gid, old_key, _ = create_family(service); path = f"/v1/families/{gid}"
    removed, retained = new_identity(), new_identity()
    removed_id, _, _ = join(service, owner, gid, old_key, removed)
    retained_id, _, _ = join(service, owner, gid, old_key, retained)
    current = post(service, owner, path + "/read", {}).json()
    manifest = copy.deepcopy(current["manifest"]); del manifest["members"][removed_id]; manifest["epoch"] += 1
    key = secrets.token_bytes(32)
    for mid, member in manifest["members"].items(): member["wrapped_key"] = wrap_key(member["encryption_key"], key, f"{gid}:2:{mid}")
    blob = encrypt(key, {"version": 1, "name": "Rotated family", "entries": {}}, f"vault-unified:family:v1:{gid}:2")
    payload = {"revision": current["revision"], "manifest": manifest, "manifest_signature": sign(owner, manifest), "removed": removed_id,
               "blob": blob, "content_signature": sign(owner, content_value(gid, 2, current["revision"] + 1, blob))}
    bad = copy.deepcopy(payload); bad["manifest"]["members"][retained_id]["wrapped_key"] = current["manifest"]["members"][retained_id]["wrapped_key"]
    bad["manifest_signature"] = sign(owner, bad["manifest"])
    assert post(service, owner, path + "/remove", bad).status_code == 400
    assert post(service, owner, path + "/remove", payload).status_code == 200
    assert post(service, removed, path + "/read", {}).status_code == 403
    assert post(service, removed, path + "/write", {}).status_code == 403
    updated = post(service, retained, path + "/read", {}).json()
    assert unwrap_key(retained, updated["manifest"]["members"][retained_id]["wrapped_key"], f"{gid}:2:{retained_id}") == key
    with pytest.raises(SharingError): decrypt(old_key, blob, f"vault-unified:family:v1:{gid}:2")
    assert post(service, owner, path + "/remove", payload).status_code == 409


def test_invitation_expiration_reuse_and_pending_approval_binding(service):
    owner, gid, key, _ = create_family(service); path = f"/v1/families/{gid}"
    invite = {"id": uuid4().hex, "secret": encode(secrets.token_bytes(32)), "role": "reader", "expires": service[3][0] + 60}
    assert post(service, owner, path + "/invite", invite).status_code == 200
    member = new_identity(); public = public_identity(member)
    payload = {"id": invite["id"], "secret": invite["secret"], "encryption_key": public["encryption_key"]}
    assert post(service, member, path + "/accept", payload).status_code == 200
    assert post(service, new_identity(), path + "/accept", payload).status_code == 410
    current = post(service, owner, path + "/read", {}).json(); manifest = current["manifest"]
    mid = member_id(public["signing_key"])
    manifest["members"][mid] = {**public, "role": "editor", "wrapped_key": wrap_key(public["encryption_key"], key, f"{gid}:1:{mid}")}
    approval = {"revision": current["revision"], "manifest": manifest, "manifest_signature": sign(owner, manifest), "pending_id": invite["id"]}
    assert post(service, owner, path + "/approve", approval).status_code == 400
    assert post(service, owner, path + "/revoke-invite", {"id": invite["id"]}).status_code == 200
    assert post(service, member, path + "/accept", payload).status_code == 410
    invite["id"] = uuid4().hex
    assert post(service, owner, path + "/invite", invite).status_code == 200
    service[3][0] += 61
    assert post(service, member, path + "/accept", {**payload, "id": invite["id"]}).status_code == 410


@pytest.mark.parametrize("url", ["http://example.com", "https://user:password@example.com", "https://example.com/a", "https://example.com#key", "file:///tmp", "https://example.com:bad"])
def test_remote_transport_rejects_unsafe_addresses(url):
    with pytest.raises(SharingError): service_url(url)


def test_envelopes_bind_recipient_and_context_and_reject_tampering():
    identity = new_identity(); other = new_identity(); key = secrets.token_bytes(32)
    envelope = wrap_key(public_identity(identity)["encryption_key"], key, "generated-context")
    assert unwrap_key(identity, envelope, "generated-context") == key
    for target, context in [(other, "generated-context"), (identity, "changed")]:
        with pytest.raises(SharingError): unwrap_key(target, envelope, context)
    blob = encrypt(key, {"generated": True}, "a")
    with pytest.raises(SharingError): decrypt(key, blob, "b")
    changed = bytearray(decode(blob)); changed[-1] ^= 1
    with pytest.raises(SharingError): decrypt(key, encode(changed), "a")


def test_service_is_separate_bounded_and_viewer_has_no_external_scripts(service):
    client, store, _, _ = service
    assert client.get("/api/entries").status_code == 404
    assert client.get("/docs").status_code == 404
    sid = uuid4().hex
    page = client.get("/s/" + sid)
    assert page.status_code == 200 and page.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
    assert "https://" not in page.text and "http://" not in page.text
    assert client.get("/assets/unknown.js").status_code == 404
    assert client.post("/v1/shares", content="{" + " " * (18 * 1024 * 1024)).status_code == 413
    assert client.post("/v1/shares", json=["generated-secret-value"]).status_code == 422


def test_quota_failure_keeps_existing_ciphertext(service):
    owner, sid, _, _, _, _ = create_share(service)
    service[1].quota = 1
    identity = new_identity(); gid, _, payload = family_data(identity)
    assert post(service, identity, "/v1/families", payload, admin=True).status_code == 507
    assert post(service, owner, f"/v1/shares/{sid}/status", {}).status_code == 200

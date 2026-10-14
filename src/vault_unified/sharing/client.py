"""Bounded HTTPS transport and verified family document operations."""
from __future__ import annotations

import copy
import json
import secrets
import socket
import ssl
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import uuid4

from .protocol import (MAX_BODY, SharingError, canonical, decrypt, encrypt, member_id, public_identity,
                       service_url, sign, signed_request, unwrap_key, validate_manifest, verify, wrap_key)
from .store import content_value


class RemoteError(SharingError):
    def __init__(self, status):
        self.status = status
        super().__init__({401: "The sharing service administration token was rejected", 403: "Shared vault access was removed or is read-only",
                         404: "Shared content was not found", 409: "Shared vault changed; refresh and review before retrying",
                         410: "The invitation or share is no longer available", 507: "Sharing service storage is full"}.get(status, "Sharing service is unavailable; retry later"))


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs): return None


class Remote:
    def __init__(self, url, identity, *, admin="", check=lambda: None):
        self.url, self.identity, self.admin, self.check = service_url(url), identity, admin, check
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def post(self, path, payload, *, creation=False):
        self.check()
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if creation: headers["Authorization"] = "Bearer " + self.admin
        data = canonical(signed_request(self.identity, path, payload))
        request = Request(self.url + path, data=data, headers=headers, method="POST")
        try:
            with self.opener.open(request, timeout=15) as response:
                body = response.read(MAX_BODY + 1)
                if response.status != 200 or len(body) > MAX_BODY: raise RemoteError(503)
                result = json.loads(body)
                if not isinstance(result, dict): raise RemoteError(503)
        except HTTPError as error:
            status = error.code; error.close(); raise RemoteError(status) from None
        except (URLError, OSError, socket.timeout, ssl.SSLError, ValueError, RecursionError):
            raise RemoteError(503) from None
        self.check()
        return result


def validate_document(value):
    if (not isinstance(value, dict) or set(value) != {"version", "name", "entries"} or value["version"] != 1
            or not isinstance(value["name"], str) or not 1 <= len(value["name"]) <= 100
            or not isinstance(value["entries"], dict) or len(value["entries"]) > 10000):
        raise SharingError("Invalid shared vault document")
    for eid, entry in value["entries"].items():
        from .protocol import identifier
        identifier(eid)
        if not isinstance(entry, dict) or set(entry) != {"title", "username", "password", "url", "notes", "updated_at", "trashed_at", "history"}:
            raise SharingError("Unsupported shared account fields")
        for name in ("title", "username", "password", "url", "notes"):
            if not isinstance(entry[name], str) or len(entry[name]) > (1000 if name == "title" else 100000): raise SharingError("Shared account text is too long")
        if not entry["title"].strip() or type(entry["updated_at"]) is not int or type(entry["trashed_at"]) is not int:
            raise SharingError("Invalid shared account")
        if not isinstance(entry["history"], list) or len(entry["history"]) > 20: raise SharingError("Invalid shared history")
        for old in entry["history"]:
            if not isinstance(old, dict) or set(old) != {"title", "username", "password", "url", "notes", "updated_at"}: raise SharingError("Invalid shared history")
            if type(old["updated_at"]) is not int or any(not isinstance(old[k], str) or len(old[k]) > 100000 for k in ("title", "username", "password", "url", "notes")):
                raise SharingError("Invalid shared history")
    canonical(value)
    return value


def create_family(identity, name):
    gid, key = uuid4().hex, secrets.token_bytes(32)
    public = public_identity(identity); mid = member_id(public["signing_key"])
    manifest = {"version": 1, "group": gid, "epoch": 1, "members": {mid: {**public, "role": "owner", "wrapped_key": wrap_key(public["encryption_key"], key, f"{gid}:1:{mid}")}}}
    document = validate_document({"version": 1, "name": name, "entries": {}})
    blob = encrypt(key, document, f"vault-unified:family:v1:{gid}:1")
    payload = {"id": gid, "manifest": manifest, "manifest_signature": sign(identity, manifest), "blob": blob,
               "content_signature": sign(identity, content_value(gid, 1, 1, blob))}
    return payload


def verify_family(identity, wire, owner, *, minimum_revision=0, minimum_epoch=1):
    try:
        from .protocol import identifier
        gid = identifier(wire["id"])
        if wire["owner"] != owner: raise SharingError("Shared vault owner changed")
        manifest = validate_manifest(wire["manifest"], owner, wire["manifest_signature"], gid)
        revision, epoch = wire["revision"], manifest["epoch"]
        if type(revision) is not int or revision < minimum_revision or epoch < minimum_epoch:
            raise SharingError("Shared vault response is older than this device")
        if type(wire["content_revision"]) is not int or not 1 <= wire["content_revision"] <= revision: raise SharingError("Invalid shared content version")
        author = next((m for m in manifest["members"].values() if m["signing_key"] == wire["author"]), None)
        if not author or author["role"] == "reader": raise SharingError("Shared content author is not an editor")
        verify(wire["author"], content_value(gid, epoch, wire["content_revision"], wire["blob"]), wire["content_signature"])
        mid = member_id(public_identity(identity)["signing_key"])
        if mid not in manifest["members"]: raise RemoteError(403)
        key = unwrap_key(identity, manifest["members"][mid]["wrapped_key"], f"{gid}:{epoch}:{mid}")
        document = validate_document(decrypt(key, wire["blob"], f"vault-unified:family:v1:{gid}:{epoch}"))
        return key, document, manifest["members"][mid]["role"]
    except (KeyError, TypeError, ValueError): raise SharingError("Shared vault response did not verify") from None


def write_proposal(identity, wire, key, document):
    document = validate_document(document)
    gid, epoch, revision = wire["id"], wire["manifest"]["epoch"], wire["revision"]
    blob = encrypt(key, document, f"vault-unified:family:v1:{gid}:{epoch}")
    return {"revision": revision, "epoch": epoch, "blob": blob,
            "content_signature": sign(identity, content_value(gid, epoch, revision + 1, blob))}


def approve_proposal(identity, wire, key, pending):
    verify_join_request(pending, wire["id"])
    gid, epoch = wire["id"], wire["manifest"]["epoch"]
    manifest = copy.deepcopy(wire["manifest"])
    public = pending["public"]; mid = member_id(public["signing_key"])
    if mid != pending["identity"] or mid in manifest["members"] or pending["role"] not in {"editor", "reader"}:
        raise SharingError("Join request identity or role changed")
    manifest["members"][mid] = {**public, "role": pending["role"], "wrapped_key": wrap_key(public["encryption_key"], key, f"{gid}:{epoch}:{mid}")}
    return {"revision": wire["revision"], "manifest": manifest, "manifest_signature": sign(identity, manifest), "pending_id": pending["id"]}


def verify_join_request(pending, gid):
    try:
        proof, public = pending["proof"], pending["public"]
        unsigned = {k: v for k, v in proof.items() if k != "signature"}
        verify(public["signing_key"], unsigned, proof["signature"])
        if (proof["version"] != 1 or proof["path"] != f"/v1/families/{gid}/accept" or proof["identity"] != public["signing_key"]
                or proof["payload"]["id"] != pending["id"] or proof["payload"]["encryption_key"] != public["encryption_key"]
                or member_id(public["signing_key"]) != pending["identity"]): raise SharingError("Invited identity proof changed")
    except (KeyError, TypeError, ValueError): raise SharingError("Invited identity proof did not verify") from None


def remove_proposal(identity, wire, document, removed):
    manifest = copy.deepcopy(wire["manifest"]); gid = wire["id"]
    if removed not in manifest["members"] or manifest["members"][removed]["role"] == "owner": raise SharingError("Choose another family member")
    del manifest["members"][removed]; manifest["epoch"] += 1
    epoch = manifest["epoch"]; key = secrets.token_bytes(32)
    for mid, member in manifest["members"].items(): member["wrapped_key"] = wrap_key(member["encryption_key"], key, f"{gid}:{epoch}:{mid}")
    blob = encrypt(key, validate_document(document), f"vault-unified:family:v1:{gid}:{epoch}")
    return {"revision": wire["revision"], "manifest": manifest, "manifest_signature": sign(identity, manifest), "removed": removed,
            "blob": blob, "content_signature": sign(identity, content_value(gid, epoch, wire["revision"] + 1, blob))}

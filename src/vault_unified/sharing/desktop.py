"""Explicit desktop sharing operations with encrypted, recoverable outbound work."""
from __future__ import annotations

import copy
import hashlib
import json
import secrets
import time
from contextlib import contextmanager
from uuid import uuid4

from vault_unified.device_keyring import get_approved_backend
from vault_unified.local_store import EntryTransactionConflict
from vault_unified.personal_sync.connections import vault_identity
from vault_unified.restore_preview import restore_preview_store
from vault_unified.session import sessions
from vault_unified.sync.preview import canonical_digest

from .client import Remote, RemoteError, approve_proposal, create_family, remove_proposal, verify_family, verify_join_request, write_proposal
from .protocol import SharingError, canonical, decode, encode, encrypt, identifier, member_id, new_identity, public_identity, service_url

NAMESPACE = "vault_unified:sharing"
CREDENTIAL_SERVICE = "vault-unified:sharing-service"
TEXT_FIELDS = {"title", "username", "password", "url", "notes"}


def state_for(local):
    if local.payload_version != 3: raise SharingError("Upgrade the vault before using sharing")
    state = local.metadata_value(NAMESPACE)
    if state is None: return {"version": 1, "identity": None, "service": "", "shares": {}, "families": {}, "outbox": {}}
    if not isinstance(state, dict) or set(state) != {"version", "identity", "service", "shares", "families", "outbox"} or state["version"] != 1:
        raise SharingError("Unsupported encrypted sharing settings")
    if state["identity"]: public_identity(state["identity"])
    for name in ("shares", "families", "outbox"):
        if not isinstance(state[name], dict) or len(state[name]) > 10000: raise SharingError("Sharing settings are too large")
    return state


def invitation(value):
    try:
        prefix, encoded = value.strip().split(".")
        if prefix != "VUF1": raise ValueError()
        data = json.loads(decode(encoded, maximum=4096))
        if set(data) != {"version", "server", "family", "id", "owner", "secret", "role"} or data["version"] != 1 or data["role"] not in {"editor", "reader"}: raise ValueError()
        service_url(data["server"]); identifier(data["family"]); identifier(data["id"]); decode(data["owner"], 32); decode(data["secret"], 32)
        return data
    except (ValueError, KeyError, TypeError): raise SharingError("Invalid family invitation code") from None


class DesktopSharing:
    def __init__(self, *, remote_factory=Remote, backend_factory=get_approved_backend):
        self.remote_factory, self.backend_factory = remote_factory, backend_factory

    @contextmanager
    def context(self, token):
        vault = sessions.get(token)
        def check():
            if sessions.get(token, touch=False) is not vault: raise PermissionError("Vault session changed")
        yield vault, check
        check()

    def commit(self, token, vault, generation, state):
        with sessions.active(token, vault), vault.local._lock:
            if vault.local.generation != generation: raise EntryTransactionConflict("Vault changed; review sharing again")
            vault.local.update_metadata(NAMESPACE, lambda _: state)

    def admin_account(self, local, server):
        return vault_identity(local) + ":" + hashlib.sha256(server.encode()).hexdigest()

    def admin(self, local, server):
        try: return self.backend_factory().get_password(CREDENTIAL_SERVICE, self.admin_account(local, server)) or ""
        except Exception: raise SharingError("Windows Credential Manager is unavailable; reconnect the sharing service") from None

    def remote(self, vault, state, server, check, *, creation=False):
        return self.remote_factory(server, state["identity"], check=check, admin=self.admin(vault.local, server) if creation else "")

    def configure(self, token, server, admin):
        server = service_url(server)
        if admin and not 32 <= len(admin) <= 256: raise SharingError("Enter the administration token from your sharing service")
        with self.context(token) as (vault, check):
            generation = vault.local.generation; state = state_for(vault.local)
            state["identity"] = state["identity"] or new_identity(); state["service"] = server
            backend = self.backend_factory(); account = self.admin_account(vault.local, server)
            old = backend.get_password(CREDENTIAL_SERVICE, account)
            try:
                if admin: backend.set_password(CREDENTIAL_SERVICE, account, admin)
                check(); self.commit(token, vault, generation, state)
            except Exception:
                if admin:
                    if old is None: backend.delete_password(CREDENTIAL_SERVICE, account)
                    else: backend.set_password(CREDENTIAL_SERVICE, account, old)
                raise
            return self.status(token)

    def status(self, token):
        with self.context(token) as (vault, _):
            state = state_for(vault.local)
            return {"service": state["service"], "identity": member_id(public_identity(state["identity"])["signing_key"]) if state["identity"] else "",
                    "shares": [{"id": sid, "title": item["title"], "server": item["server"], "expires": item["payload"]["expires"],
                                "max_reads": item["payload"]["max_reads"], "phase": item["phase"], "reads": item.get("reads", 0)} for sid, item in state["shares"].items()],
                    "families": [{"id": gid, "name": item["name"], "server": item["server"], "pending": item.get("pending", False),
                                  "revision": (item.get("wire") or {}).get("revision", 0), "removed": item.get("removed", False)} for gid, item in state["families"].items()],
                    "outbox": [{"id": oid, "action": item["action"], "title": item["title"], "family": item.get("family", "")} for oid, item in state["outbox"].items()]}

    def family(self, state, gid):
        identifier(gid)
        item = state["families"].get(gid)
        if not item or item.get("removed"): raise SharingError("Refresh or rejoin this shared vault")
        if not item.get("wire"): raise SharingError("Wait for the owner to approve, then refresh")
        key, document, role = verify_family(state["identity"], item["wire"], item["owner"])
        return item, key, document, role

    def view(self, token, gid, *, entry_id="", reveal=False):
        with self.context(token) as (vault, _):
            state = state_for(vault.local); item, _, document, role = self.family(state, gid)
            if entry_id:
                entry = document["entries"].get(identifier(entry_id))
                if not entry: raise SharingError("Shared account no longer exists")
                return copy.deepcopy(entry) if reveal else {**entry, "password": "", "notes": "", "history": []}
            return {"id": gid, "name": document["name"], "role": role, "revision": item["wire"]["revision"],
                    "members": [{"id": mid, "role": m["role"]} for mid, m in item["wire"]["manifest"]["members"].items()],
                    "entries": [{"id": eid, "title": e["title"], "username": e["username"], "url": e["url"], "trashed_at": e["trashed_at"], "history_count": len(e["history"])} for eid, e in document["entries"].items()]}

    def refresh(self, token, gid):
        with self.context(token) as (vault, check):
            state = state_for(vault.local); item = state["families"].get(identifier(gid))
            if not item: raise SharingError("Shared vault is not connected")
            generation = vault.local.generation
            remote = self.remote(vault, state, item["server"], check)
            try:
                if item.get("pending"):
                    result = remote.post(f"/v1/families/{gid}/status", {})
                    if result.get("pending"): return {"pending": True}
                wire = remote.post(f"/v1/families/{gid}/read", {})
                old = item.get("wire") or {}
                _, document, _ = verify_family(state["identity"], wire, item["owner"], minimum_revision=old.get("revision", 0), minimum_epoch=old.get("manifest", {}).get("epoch", 1))
                if wire["id"] != gid: raise SharingError("Shared vault identity changed")
                item.update(wire=wire, name=document["name"], pending=False, removed=False)
            except RemoteError as error:
                if error.status == 403:
                    item.update(wire=None, removed=True, pending=False)
                    self.commit(token, vault, generation, state)
                raise
            self.commit(token, vault, generation, state)
            return {"pending": False, "revision": wire["revision"]}

    def pending_members(self, token, gid, *, internal=False):
        with self.context(token) as (vault, check):
            state = state_for(vault.local); item, _, _, role = self.family(state, gid)
            if role != "owner": raise SharingError("Only the family owner can manage members")
            result = self.remote(vault, state, item["server"], check).post(f"/v1/families/{gid}/pending", {})
            for request in result["requests"]: verify_join_request(request, gid)
            if not internal:
                result["requests"] = [{k: v for k, v in request.items() if k != "proof"} for request in result["requests"]]
            return result

    def preview(self, token, options):
        with self.context(token) as (vault, check):
            generation = vault.local.generation; state = state_for(vault.local)
            action, gid = options["action"], options.get("family_id", "")
            if options.get("replace_pending_id") and action != "save-entry": raise SharingError("Only an account draft can replace a pending proposal")
            title, details, server = "", [], state["service"]
            if action == "share":
                entry = vault.local.get(options["entry_id"])
                from vault_unified.organization import is_fillable
                if not entry or not is_fillable(entry): raise SharingError("Choose an active personal account")
                chosen = options["fields"]
                if not chosen or len(set(chosen)) != len(chosen) or set(chosen) - (TEXT_FIELDS - {"title"}): raise SharingError("Select the fields to share")
                title, details = entry.title, chosen
            elif action == "create-family": title = options["name"].strip()
            elif action == "join-family":
                invite = invitation(options["invite"]); server = invite["server"]
                title, details = "", [member_id(invite["owner"]), invite["role"]]
            elif action == "revoke-share":
                share = state["shares"].get(identifier(options["entry_id"]))
                if not share: raise SharingError("Share not found")
                server, title = share["server"], share["title"]
            else:
                item, _, document, role = self.family(state, gid); server, title = item["server"], item["name"]
                if role == "reader": raise SharingError("This shared vault is read-only")
                if action in {"invite", "approve-member", "remove-member", "revoke-invite"} and role != "owner": raise SharingError("Only the family owner can manage members")
                replacement = options.get("replace_pending_id", "")
                if replacement:
                    old_op = state["outbox"].get(replacement)
                    if not old_op or old_op.get("family") != gid or not old_op.get("draft") or action != "save-entry":
                        raise SharingError("Pending proposal changed; review it again")
                if any(op.get("family") == gid and oid != replacement for oid, op in state["outbox"].items()): raise SharingError("Finish or discard the pending operation for this shared vault")
                if action == "approve-member":
                    pending = self.pending_members(token, gid, internal=True)
                    request = next((r for r in pending["requests"] if r["id"] == options["pending_id"]), None)
                    if not request: raise SharingError("Join request is no longer pending")
                    details = [request["identity"], request["role"]]
                elif action == "remove-member":
                    member = item["wire"]["manifest"]["members"].get(options["member_id"])
                    if not member or member["role"] == "owner": raise SharingError("Choose another family member")
                    details = [options["member_id"], member["role"]]
                elif action == "save-entry":
                    values = options["values"]
                    if set(values) != TEXT_FIELDS or any(not isinstance(v, str) or len(v) > 100000 for v in values.values()) or not values["title"].strip() or len(values["title"]) > 1000:
                        raise SharingError("Complete the shared account fields")
                    title, details = values["title"], sorted(TEXT_FIELDS)
                elif action in {"trash-entry", "restore-entry", "restore-history"}:
                    entry = document["entries"].get(identifier(options["entry_id"]))
                    if not entry: raise SharingError("Shared account no longer exists")
                    if action == "restore-history" and not 0 <= options["history_index"] < len(entry["history"]): raise SharingError("Shared history version no longer exists")
                    title = entry["title"]
            service_url(server)
            if action == "create-family" and not 1 <= len(title) <= 100: raise SharingError("Enter a shared vault name")
            check()
            intent = restore_preview_store.issue(scope=token, kind="sharing", source_path="", source_sha256=canonical_digest(options),
                active_sha256="", active_state_digest="", active_generation=generation)
            return {"preview_token": intent.token, "action": action, "title": title, "server": server, "details": details}

    def cancel(self, token, preview_token):
        with self.context(token):
            restore_preview_store.consume(preview_token, scope=token, kind="sharing")

    def apply(self, token, preview_token, options):
        with self.context(token) as (vault, check):
            intent = restore_preview_store.consume(preview_token, scope=token, kind="sharing")
            if intent.source_sha256 != canonical_digest(options): raise SharingError("Sharing selection changed after preview")
            if vault.local.generation != intent.active_generation: raise EntryTransactionConflict("Vault changed after sharing preview")
            state = state_for(vault.local); state["identity"] = state["identity"] or new_identity()
            action = options["action"]; oid = uuid4().hex; now = int(time.time())
            op = {"action": action, "server": state["service"], "creation": False, "family": options.get("family_id", ""), "title": options.get("name", "")}
            if action == "share":
                entry = vault.local.get(options["entry_id"]); sid, key, cap = uuid4().hex, secrets.token_bytes(32), encode(secrets.token_bytes(32))
                expires = now + options["hours"] * 3600
                plain = {"version": 1, "id": sid, "title": entry.title, "expires": expires, "fields": {name: getattr(entry, name) for name in options["fields"]}}
                payload = {"id": sid, "capability": cap, "blob": encrypt(key, plain, "vault-unified:share:v1:" + sid), "expires": expires, "max_reads": options["max_reads"]}
                state["shares"][sid] = {"title": entry.title, "server": state["service"], "key": encode(key), "payload": payload, "phase": "pending"}
                op.update(path="/v1/shares", payload=payload, creation=True, share=sid, title=entry.title)
            elif action == "revoke-share":
                sid = options["entry_id"]; item = state["shares"][sid]
                # Cancelling a not-yet-acknowledged create must never retry its upload.
                state["outbox"] = {k: v for k, v in state["outbox"].items() if v.get("share") != sid}
                item["phase"] = "revoking"
                op.update(server=item["server"], path=f"/v1/shares/{sid}/revoke", payload={}, share=sid, title=item["title"], creation=True)
            elif action == "create-family":
                payload = create_family(state["identity"], options["name"].strip()); gid = payload["id"]
                state["families"][gid] = {"server": state["service"], "name": options["name"].strip(), "owner": public_identity(state["identity"])["signing_key"], "wire": None, "pending": False}
                op.update(path="/v1/families", payload=payload, creation=True, family=gid)
            elif action == "join-family":
                invite = invitation(options["invite"]); gid = invite["family"]
                if gid in state["families"] and not state["families"][gid].get("removed"): raise SharingError("This shared vault is already connected")
                state["families"][gid] = {"server": invite["server"], "name": "", "owner": invite["owner"], "wire": None, "pending": True}
                op.update(server=invite["server"], path=f"/v1/families/{gid}/accept", family=gid, payload={"id": invite["id"], "secret": invite["secret"], "encryption_key": public_identity(state["identity"])["encryption_key"]})
            else:
                gid = options["family_id"]; item, key, document, role = self.family(state, gid); wire = item["wire"]
                op.update(server=item["server"], title=item["name"])
                if action == "invite":
                    iid, secret = uuid4().hex, encode(secrets.token_bytes(32))
                    op.update(path=f"/v1/families/{gid}/invite", payload={"id": iid, "secret": secret, "role": options["role"], "expires": now + 86400})
                    code = {"version": 1, "server": item["server"], "family": gid, "id": iid, "owner": item["owner"], "secret": secret, "role": options["role"]}
                    op["invitation"] = "VUF1." + encode(canonical(code))
                elif action == "revoke-invite": op.update(path=f"/v1/families/{gid}/revoke-invite", payload={"id": options["pending_id"]})
                elif action == "approve-member":
                    pending = self.pending_members(token, gid, internal=True)
                    request = next((r for r in pending["requests"] if r["id"] == options["pending_id"]), None)
                    if not request: raise SharingError("Join request is no longer pending")
                    # Identity/role are also bound by the exact previewed options below.
                    if request["identity"] != options["member_id"] or request["role"] != options["role"]: raise SharingError("Join request changed; preview again")
                    op.update(path=f"/v1/families/{gid}/approve", payload=approve_proposal(state["identity"], wire, key, request))
                elif action == "remove-member": op.update(path=f"/v1/families/{gid}/remove", payload=remove_proposal(state["identity"], wire, document, options["member_id"]))
                else:
                    eid = options["entry_id"] or uuid4().hex; old = document["entries"].get(eid)
                    if action == "save-entry":
                        if options["entry_id"] and old is None: raise SharingError("Shared account no longer exists")
                        history = (([{k: old[k] for k in (*TEXT_FIELDS, "updated_at")}] + old["history"])[:20] if old else [])
                        document["entries"][eid] = {**options["values"], "updated_at": now, "trashed_at": old["trashed_at"] if old else 0, "history": history}
                    elif action == "restore-history":
                        chosen = old["history"][options["history_index"]]
                        history = ([{k: old[k] for k in (*TEXT_FIELDS, "updated_at")}] + old["history"])[:20]
                        document["entries"][eid] = {**chosen, "updated_at": now, "trashed_at": old["trashed_at"], "history": history}
                    else: old["trashed_at"] = now if action == "trash-entry" else 0
                    document["entries"] = {k: v for k, v in document["entries"].items() if not v["trashed_at"] or now - v["trashed_at"] < 30 * 86400}
                    if action in {"save-entry", "restore-history"}:
                        op["draft"] = {"action": "save-entry", "family_id": gid, "entry_id": eid, "values": {k: document["entries"][eid][k] for k in TEXT_FIELDS}}
                    op.update(path=f"/v1/families/{gid}/write", payload=write_proposal(state["identity"], wire, key, document))
            if options.get("replace_pending_id"): state["outbox"].pop(options["replace_pending_id"])
            state["outbox"][oid] = op
            check(); self.commit(token, vault, intent.active_generation, state)
        return self.retry(token, oid)

    def retry(self, token, oid):
        with self.context(token) as (vault, check):
            state = state_for(vault.local); op = state["outbox"].get(identifier(oid))
            if not op: raise SharingError("Pending sharing operation no longer exists")
            generation = vault.local.generation
            remote = self.remote(vault, state, op["server"], check, creation=op["creation"])
            try: result = remote.post(op["path"], op["payload"], creation=op["creation"])
            except RemoteError as error:
                if error.status not in {409, 410} or op["action"] not in {"save-entry", "trash-entry", "restore-entry", "restore-history", "approve-member", "remove-member"}: raise
                # A previous response may have been lost after its atomic commit.
                wire = remote.post(f"/v1/families/{op['family']}/read", {})
                item = state["families"][op["family"]]
                verify_family(state["identity"], wire, item["owner"])
                matches = (wire["manifest"] == op["payload"]["manifest"] if "manifest" in op["payload"] else wire["blob"] == op["payload"]["blob"])
                if not matches or wire["revision"] < op["payload"]["revision"] + 1: raise error
                result = {"revision": wire["revision"]}
            response = {"completed": True, "action": op["action"]}
            if op.get("share"):
                item = state["shares"][op["share"]]
                item.update(phase="revoked" if result.get("revoked") else "ready", reads=result.get("reads", 0))
                if item["phase"] == "revoked": item["key"] = ""; item["payload"]["blob"] = ""; item["payload"]["capability"] = ""
            if op["action"] == "invite": response["invitation"] = op["invitation"]
            if op["family"]:
                item = state["families"][op["family"]]
                if op["action"] == "join-family":
                    if result.get("owner") != item["owner"]: raise SharingError("Invitation owner did not verify")
                    item["pending"] = result.get("pending", True)
                if not item.get("pending"):
                    wire = remote.post(f"/v1/families/{op['family']}/read", {})
                    old = item.get("wire") or {}
                    _, document, _ = verify_family(state["identity"], wire, item["owner"], minimum_revision=old.get("revision", 0), minimum_epoch=old.get("manifest", {}).get("epoch", 1))
                    if wire["id"] != op["family"]: raise SharingError("Shared vault identity changed")
                    item.update(wire=wire, name=document["name"])
            state["outbox"].pop(oid)
            self.commit(token, vault, generation, state)
            return response

    def discard(self, token, oid):
        with self.context(token) as (vault, _):
            state = state_for(vault.local); generation = vault.local.generation
            op = state["outbox"].get(identifier(oid))
            if not op: return {"discarded": True}
            if op.get("share"): raise SharingError("Revoke the pending share before discarding it")
            # Remote success may have preceded a lost response; refresh before discarding.
            if op["family"] and op["action"] not in {"join-family", "create-family"}: self.refresh(token, op["family"])
            generation = vault.local.generation; state = state_for(vault.local)
            state["outbox"].pop(oid, None)
            self.commit(token, vault, generation, state)
            return {"discarded": True}

    def review_pending(self, token, oid):
        with self.context(token) as (vault, _):
            op = state_for(vault.local)["outbox"].get(identifier(oid))
            if not op or not op.get("draft"): raise SharingError("This operation has no editable account draft")
            self.refresh(token, op["family"])
            state = state_for(vault.local); item, _, document, role = self.family(state, op["family"])
            if role == "reader": raise SharingError("This shared vault is read-only")
            options = copy.deepcopy(op["draft"]); current = document["entries"].get(options["entry_id"])
            if not current: options["entry_id"] = ""
            options["replace_pending_id"] = oid
            return {"options": options, "current": {k: current[k] for k in TEXT_FIELDS} if current else None}

    def link(self, token, sid):
        with self.context(token) as (vault, _):
            state = state_for(vault.local); item = state["shares"].get(identifier(sid))
            if not item or item["phase"] != "ready" or item["payload"]["expires"] <= int(time.time()): raise SharingError("Share is not available")
            return item["server"] + "/s/" + sid + "#key=" + item["key"] + "&cap=" + item["payload"]["capability"]


sharing = DesktopSharing()

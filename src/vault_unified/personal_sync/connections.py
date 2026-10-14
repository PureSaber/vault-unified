"""Explicit connection approval, installation binding and Windows credentials."""
from __future__ import annotations

import base64
import copy
import json
import secrets
import threading
import time
from pathlib import Path
from uuid import uuid4

from vault_unified.backup_manager import create_manual_backup
from vault_unified.config import get_config_dir
from vault_unified.device_keyring import get_approved_backend
from vault_unified.local_store import EntryTransactionConflict
from vault_unified.personal_sync.codec import STATE_NAMESPACE, ProtocolError, identifier
from vault_unified.personal_sync.engine import download, run, resolve
from vault_unified.personal_sync.payload import project, materialize
from vault_unified.personal_sync.replica import initial, queue, receive, pending_deletions
from vault_unified.personal_sync.transport import FolderStore, WebDAVStore, StorageUnavailable
from vault_unified.storage import atomic_write_bytes, ConcurrentStorageChangeError
from vault_unified.v3_crypto import validate_v3_payload
from vault_unified.vault_format import V3Container, inspect_vault_format_file

SERVICE = "vault-unified:personal-sync"


def encode_key(key: bytes) -> str:
    return base64.urlsafe_b64encode(key).rstrip(b"=").decode("ascii")


def decode_key(value: str) -> bytes:
    try:
        key = base64.b64decode(value + "=", altchars=b"-_", validate=True)
        if len(key) != 32 or encode_key(key) != value: raise ValueError()
        return key
    except Exception:
        raise ProtocolError("Invalid synchronization connection code") from None


def parse_code(value: str) -> tuple[str, bytes]:
    try:
        prefix, space, encoded = value.strip().split(".")
        if prefix != "VUS1": raise ValueError()
        return identifier(space), decode_key(encoded)
    except Exception:
        raise ProtocolError("Invalid synchronization connection code") from None


def vault_identity(local) -> str:
    container = inspect_vault_format_file(local.vault_path)
    if local.payload_version != 3 or not isinstance(container, V3Container):
        raise ProtocolError("Upgrade the vault before enabling synchronization")
    return container.header.vault_id


class Connections:
    def __init__(self, *, config_dir: Path | None = None, backend_factory=None):
        self.config_dir, self.backend_factory = config_dir, backend_factory
        self._previews = {}
        self._guard = threading.Lock()
        self._busy = set()
        self._results = {}

    def _backend(self):
        try:
            return (self.backend_factory or get_approved_backend)()
        except Exception:
            raise StorageUnavailable("Windows Credential Manager is unavailable") from None

    def _installation(self, *, create=False) -> str | None:
        path = (self.config_dir or get_config_dir()) / "sync-installation.json"
        try:
            if path.exists():
                if path.is_symlink() or path.stat().st_size > 256: raise ValueError()
                value = json.loads(path.read_text(encoding="utf-8"))
                if set(value) != {"version", "id"} or value["version"] != 1: raise ValueError()
                return identifier(value["id"])
            if not create: return None
            identity = uuid4().hex
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                atomic_write_bytes(path, json.dumps({"version": 1, "id": identity}).encode(), must_not_exist=True)
            except ConcurrentStorageChangeError:
                return self._installation()
            return identity
        except Exception:
            raise StorageUnavailable("Local synchronization identity is unavailable") from None

    @staticmethod
    def _account(connection):
        return identifier(connection["installation"]) + ":" + identifier(connection["device"])

    def _bound(self, local, state) -> bool:
        connection = state.get("connection", {}) if isinstance(state, dict) else {}
        return bool(connection and connection.get("installation") == self._installation()
                    and connection.get("vault_id") == vault_identity(local)
                    and connection.get("vault_path") == str(local.vault_path.resolve()))

    def _credentials(self, local, state=None):
        state = state or local.metadata_value(STATE_NAMESPACE)
        if not self._bound(local, state) or state["connection"].get("disabled"):
            raise ProtocolError("Connect this computer to synchronization storage first")
        try:
            value = self._backend().get_password(SERVICE, self._account(state["connection"]))
            secret = json.loads(value)
            if set(secret) != {"key", "username", "password"}: raise ValueError()
            key = decode_key(secret["key"])
            if any(not isinstance(secret[name], str) for name in ("username", "password")): raise ValueError()
            return state, key, secret
        except Exception:
            raise StorageUnavailable("Synchronization credentials are unavailable; reconnect this computer") from None

    @staticmethod
    def _store(connection, secret, *, create=False):
        if connection["provider"] == "folder":
            return FolderStore(connection["location"], connection["space"], create=create)
        if connection["provider"] == "webdav":
            return WebDAVStore(connection["location"], connection["space"], secret["username"], secret["password"], create=create)
        raise ProtocolError("Unsupported synchronization storage")

    def clear_scope(self, scope):
        with self._guard:
            self._previews = {key: value for key, value in self._previews.items() if scope is not None and value["scope"] != scope}

    def preview(self, local, scope, options, check=lambda: None):
        if self._bound(local, local.metadata_value(STATE_NAMESPACE)):
            raise ProtocolError("Disconnect the current connection before choosing another")
        self._backend()
        if options["provider"] not in {"folder", "webdav"}: raise ProtocolError("Choose folder or WebDAV storage")
        if options["mode"] == "join":
            space, key = parse_code(options["code"])
        elif options["mode"] == "create":
            space, key = uuid4().hex, secrets.token_bytes(32)
        else: raise ProtocolError("Choose create or join")
        location, label = options["location"].strip(), options["label"].strip()
        if not location or not 1 <= len(label) <= 100: raise ProtocolError("Storage location and device name are required")
        if options["provider"] == "folder":
            folder = Path(location).expanduser().resolve()
            if not folder.is_dir(): raise StorageUnavailable("Choose an existing synchronization folder")
            location = str(folder)
        device = uuid4().hex
        connection = {"provider": options["provider"], "location": location, "space": space, "device": device,
                      "label": label, "automatic": bool(options["automatic"]), "vault_id": vault_identity(local),
                      "vault_path": str(local.vault_path.resolve()), "installation": "", "disabled": False}
        secret = {"key": encode_key(key), "username": options.get("username", ""), "password": options.get("password", "")}
        if len(json.dumps(secret, ensure_ascii=False).encode("utf-16-le")) > 2400:
            raise ProtocolError("WebDAV credentials exceed the Windows storage limit")
        generation, payload = local.sync_snapshot()
        objects = project(payload)
        state = initial(space, device); state["connection"] = connection
        state = queue(state, objects, key, label)
        if options["mode"] == "join":
            store = self._store(connection, secret)
            downloaded = 0
            while True:
                records, more = download(store, state, key, check)
                previous = state["seen"]
                state, objects, waiting = receive(state, objects, records)
                downloaded += len(records)
                validate_v3_payload(materialize(payload, objects, state))
                if not more:
                    if waiting or not downloaded: raise ProtocolError("Synchronization history is empty or incomplete; retry after the other computer syncs")
                    break
                if state["seen"] == previous: raise ProtocolError("Synchronization history is missing required changes")
        elif options["provider"] == "webdav":
            # Validate the HTTPS address before issuing any approved create call.
            self._store(connection, secret)
        candidate = materialize(payload, objects, state)
        validate_v3_payload(candidate)
        check()
        if local.generation != generation: raise EntryTransactionConflict("Vault changed during connection preview; retry")
        before = project(payload)
        items = []
        for object_id in sorted(before.keys() | objects.keys()):
            old, new = before.get(object_id), objects.get(object_id)
            if old == new: continue
            items.append({"id": object_id, "title": (new or old).get("title", ""),
                          "action": "add" if old is None else "remove" if new is None else "update"})
        token = secrets.token_urlsafe(32)
        with self._guard:
            self._previews = {key: value for key, value in self._previews.items() if value["expires"] > time.monotonic() and value["scope"] != scope}
            if len(self._previews) >= 4: raise ProtocolError("Close another connection preview first")
            self._previews[token] = {"scope": scope, "expires": time.monotonic() + 300, "generation": generation,
                                     "candidate": candidate, "secret": secret, "create": options["mode"] == "create",
                                     "backup": bool(items)}
        return {"preview_token": token, "items": items[:100], "total": len(items), "conflicts": len(state["conflicts"]),
                "local_entries": len(payload["entries"]), "result_entries": sum(key.startswith("entry/") for key in objects),
                "provider": connection["provider"], "location": location, "automatic": connection["automatic"]}

    def cancel(self, scope, token):
        with self._guard:
            if token in self._previews and self._previews[token]["scope"] == scope:
                self._previews.pop(token)

    def apply(self, local, scope, token, check=lambda: None):
        with self._guard:
            preview = self._previews.get(token)
            if preview is None or preview["scope"] != scope or preview["expires"] <= time.monotonic():
                raise ProtocolError("Connection preview expired; create a new preview")
            self._previews.pop(token)
        check()
        if local.generation != preview["generation"]: raise EntryTransactionConflict("Vault changed after preview; create a new preview")
        candidate = preview["candidate"]
        connection = candidate["metadata"][STATE_NAMESPACE]["connection"]
        connection["installation"] = self._installation(create=True)
        backend = self._backend(); account = self._account(connection)
        backup = ""
        if preview["backup"]:
            backup = str(create_manual_backup(local.vault_path, local.credential).path)
        try:
            backend.set_password(SERVICE, account, json.dumps(preview["secret"], ensure_ascii=False))
        except Exception:
            raise StorageUnavailable("Could not save synchronization credentials in Windows Credential Manager") from None
        try:
            self._store(connection, preview["secret"], create=preview["create"])
            check()
            local.commit_sync_payload(candidate, expected_generation=preview["generation"])
        except Exception:
            try: backend.delete_password(SERVICE, account)
            except Exception:
                raise StorageUnavailable(f"Connection was not activated. Remove the pending Windows credential for {SERVICE}, account {account}") from None
            raise
        return {"connected": True, "backup_path": backup}

    def code(self, local):
        state, key, _ = self._credentials(local)
        return "VUS1." + state["space"] + "." + encode_key(key)

    def status(self, local):
        generation, payload = local.sync_snapshot()
        state = payload.get("metadata", {}).get(STATE_NAMESPACE)
        bound = self._bound(local, state)
        if not bound: return {"connected": False, "reconnect": bool(state), "generation": generation, "upgrade_required": local.payload_version < 3}
        connection = state["connection"]
        objects = project(payload)
        pending = sum(state["baseline"].get(key) != value for key, value in objects.items())
        pending += sum(key not in objects for key in state["baseline"])
        with self._guard:
            result = copy.deepcopy(self._results.get(connection["device"], {}))
            busy = str(local.vault_path.resolve()) in self._busy
        return {**result, "connected": True, "generation": generation, "provider": connection["provider"], "location": connection["location"],
                "label": connection["label"], "automatic": connection["automatic"], "disabled": connection.get("disabled", False),
                "pending": pending, "outbox": len(state["outbox"]), "conflicts": len(state["conflicts"]),
                "pending_deletions": pending_deletions(state), "devices": [{"id": key, "label": value["label"], "current": key == state["device"]} for key, value in state["members"].items()],
                "busy": busy}

    def synchronize(self, local, check=lambda: None, *, automatic=False):
        current = local.metadata_value(STATE_NAMESPACE)
        if automatic and (not self._bound(local, current) or current["connection"].get("disabled")
                          or not current["connection"]["automatic"]):
            return {"skipped": True}
        if automatic and current["conflicts"]:
            return {"skipped": True, "conflicts": len(current["conflicts"])}
        state, key, secret = self._credentials(local)
        path = str(local.vault_path.resolve())
        with self._guard:
            if path in self._busy: return {"busy": True}
            self._busy.add(path)
        try:
            result = run(local, self._store(state["connection"], secret), key, check=check)
            with self._guard: self._results[state["device"]] = {"last_success": time.time(), "error": "", **result}
            return result
        except (StorageUnavailable, ProtocolError, EntryTransactionConflict) as error:
            with self._guard: self._results[state["device"]] = {"error": str(error)}
            raise
        finally:
            with self._guard: self._busy.discard(path)

    def settings(self, local, *, automatic: bool, label: str):
        generation, payload = local.sync_snapshot()
        state = payload.get("metadata", {}).get(STATE_NAMESPACE)
        if not self._bound(local, state): raise ProtocolError("Connect this computer first")
        if not label.strip() or len(label) > 100: raise ProtocolError("Enter a device name")
        state["connection"].update(automatic=automatic, label=label.strip())
        local.commit_sync_payload(payload, expected_generation=generation)

    def disconnect(self, local):
        generation, payload = local.sync_snapshot()
        state = payload.get("metadata", {}).get(STATE_NAMESPACE)
        if state is None: return {"disconnected": True}
        if self._bound(local, state):
            state["connection"]["disabled"] = True
            local.commit_sync_payload(payload, expected_generation=generation)
            generation += 1
            try:
                backend = self._backend(); account = self._account(state["connection"])
                if backend.get_password(SERVICE, account) is not None: backend.delete_password(SERVICE, account)
            except Exception:
                return {"disconnected": True, "cleanup_pending": True}
        payload["metadata"].pop(STATE_NAMESPACE)
        local.commit_sync_payload(payload, expected_generation=generation)
        return {"disconnected": True, "cleanup_pending": False}

    def resolve(self, local, choices, generation):
        _, key, _ = self._credentials(local)
        resolve(local, key, choices, expected_generation=generation)

    def conflicts(self, local, *, reveal=False):
        generation, payload = local.sync_snapshot()
        state = payload.get("metadata", {}).get(STATE_NAMESPACE)
        if not self._bound(local, state): return {"generation": generation, "items": []}
        objects = project(payload)
        items = []
        def display(present, value, root=False):
            if not present: return {"present": False, "value": ""}
            if root:
                if not isinstance(value, dict): raise ProtocolError("Invalid conflict value")
                return {"present": True, "value": str(value.get("title", "")), "state": value.get("source_metadata", {}).get("vault_unified:organization", {}).get("state", "active")}
            if not reveal: return {"present": True, "value": "••••••••"}
            text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            return {"present": True, "value": text[:4000], "truncated": len(text) > 4000}
        for conflict in state["conflicts"].values():
            object_id, path = conflict["object"], conflict["path"]
            current = objects.get(object_id)
            present = current is not None
            title = (current or conflict["remote"].get("value") or conflict["local"].get("value") or {}).get("title", "") if not path else (objects.get(object_id) or {}).get("title", "")
            for part in path:
                if not isinstance(current, dict) or part not in current:
                    present, current = False, None; break
                current = current[part]
            items.append({"id": conflict["id"], "object": object_id, "title": title, "path": path, "kind": conflict["kind"],
                          "device": state["members"].get(conflict["device"], {}).get("label", ""),
                          "local": display(present, current, not path),
                          "remote": display(conflict["remote"]["present"], conflict["remote"].get("value"), not path)})
        return {"generation": generation, "items": items}


connections = Connections()

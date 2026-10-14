from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock, Thread
from uuid import uuid4
from xml.sax.saxutils import escape
import secrets

import pytest

from vault_unified.personal_sync.codec import filename, ProtocolError
from vault_unified.personal_sync.transport import FolderStore, WebDAVStore, StorageUnavailable


@contextmanager
def generated_webdav():
    state = {"files": {}, "requests": [], "mode": "normal", "lock": Lock()}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def reply(self, status, body=b"", headers=None):
            self.send_response(status)
            for name, value in (headers or {}).items(): self.send_header(name, value)
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        def track(self):
            state["requests"].append((self.command, self.path, dict(self.headers)))
            return self.path.rsplit("/", 1)[-1]
        def do_MKCOL(self): self.track(); self.reply(201)
        def do_PROPFIND(self):
            self.track()
            if state["mode"] == "foreign-list":
                body = b'<d:multistatus xmlns:d="DAV:"><d:response><d:href>https://elsewhere.invalid/record</d:href></d:response></d:multistatus>'
            else:
                records = "".join(f"<d:response><d:href>{escape(self.path + name)}</d:href></d:response>" for name in state["files"])
                body = (f'<d:multistatus xmlns:d="DAV:">{records}</d:multistatus>').encode()
            self.reply(207, body)
        def do_GET(self):
            name = self.track()
            if state["mode"] == "redirect": return self.reply(302, headers={"Location": "/outside"})
            if name in state["files"]: self.reply(200, state["files"][name])
            else: self.reply(404)
        def do_PUT(self):
            name = self.track(); body = self.rfile.read(int(self.headers["Content-Length"]))
            with state["lock"]:
                if name in state["files"]:
                    assert self.headers.get("If-None-Match") == "*"
                    return self.reply(412)
                state["files"][name] = body[:-1] if state["mode"] == "truncate" else body
            self.reply(201)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True); thread.start()
    try: yield f"http://127.0.0.1:{server.server_port}/generated/", state
    finally: server.shutdown(); server.server_close(); thread.join()


def test_folder_retry_and_collision_never_overwrite_a_device_change(tmp_path):
    space, device = uuid4().hex, uuid4().hex
    store = FolderStore(tmp_path, space, create=True)
    name = filename(device, 1); value = secrets.token_bytes(100)
    store.put(name, value); store.put(name, value)
    assert store.list() == [name] and store.get(name) == value
    with pytest.raises(StorageUnavailable): store.put(name, secrets.token_bytes(100))
    assert store.get(name) == value
    assert [item.name for item in store.root.iterdir()] == [name]
    with pytest.raises(ProtocolError): store.get("../generated-private-file")


def test_actual_http_webdav_creation_listing_roundtrip_retry_and_collision():
    with generated_webdav() as (address, state):
        store = WebDAVStore(address, uuid4().hex, "generated", secrets.token_hex(20), create=True)
        name, value = filename(uuid4().hex, 1), secrets.token_bytes(100)
        store.put(name, value); store.put(name, value)
        assert store.list() == [name] and store.get(name) == value
        writes = [request for request in state["requests"] if request[0] == "PUT"]
        assert len(writes) == 1 and writes[0][2]["If-None-Match"] == "*"
        propfind = next(request for request in state["requests"] if request[0] == "PROPFIND")
        assert propfind[2]["Depth"] == "1"
        with pytest.raises(StorageUnavailable): store.put(name, b"generated conflicting bytes")
        assert state["files"][name] == value


@pytest.mark.parametrize("mode", ["redirect", "foreign-list", "truncate"])
def test_webdav_failure_never_accepts_redirects_foreign_paths_or_truncated_uploads(mode):
    with generated_webdav() as (address, state):
        password = secrets.token_hex(24)
        store = WebDAVStore(address, uuid4().hex, "generated", password, create=True)
        state["mode"] = mode
        with pytest.raises(StorageUnavailable) as failure:
            if mode == "foreign-list": store.list()
            elif mode == "truncate": store.put(filename(uuid4().hex, 1), secrets.token_bytes(100))
            else: store.get(filename(uuid4().hex, 1))
        assert password not in str(failure.value) and address not in str(failure.value)
        assert all(request[1] != "/outside" for request in state["requests"])


@pytest.mark.parametrize("address", ["http://nas.example.test/", "https://user:secret@example.test/", "https://example.test/?token=generated", "file:///generated", "https://example.test/#fragment"])
def test_unencrypted_or_credential_bearing_remote_addresses_are_refused(address):
    with pytest.raises(StorageUnavailable): WebDAVStore(address, uuid4().hex, "generated", "generated", create=False)

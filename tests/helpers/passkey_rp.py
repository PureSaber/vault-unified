"""Ephemeral localhost RP for generated browser journeys; no files or accounts."""
import json
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from fido2.server import Fido2Server

rp = Fido2Server({"id": "localhost", "name": "Generated Passkey website"})
states = {}
credentials = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass

    def send(self, value, status=200):
        data = json.dumps(value).encode()
        self.send_response(status); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

    def do_GET(self):
        if self.path != "/": self.send({}, 404); return
        data = Path(__file__).with_suffix(".html").read_bytes()
        self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 <= length <= 65536: raise ValueError()
            body = json.loads(self.rfile.read(length))
            if self.path == "/create/options":
                options, state = rp.register_begin({"id": secrets.token_bytes(16), "name": "generated-user", "displayName": "Generated account"}, credentials, user_verification="required", resident_key_requirement="required", extensions={"credProps": True})
            elif self.path == "/get/options":
                options, state = rp.authenticate_begin(None if body.get("discoverable") else credentials[-1:], user_verification="required")
            elif self.path in {"/create/verify", "/get/verify"}:
                state = states.pop(body["state"])
                if self.path.startswith("/create/"):
                    credentials.append(rp.register_complete(state, body["credential"]).credential_data)
                else:
                    rp.authenticate_complete(state, credentials, body["credential"])
                self.send({"verified": True, "count": len(credentials)}); return
            else: self.send({}, 404); return
            identifier = secrets.token_hex(24); states[identifier] = state
            self.send({"state": identifier, "options": dict(options)["publicKey"]})
        except Exception:
            self.send({"verified": False}, 400)


server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
print(json.dumps({"port": server.server_port}), flush=True)
server.serve_forever()

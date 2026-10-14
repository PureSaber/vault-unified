"""Ephemeral generated-data service for browser verification, never real profiles."""
import json
import os
import secrets
import socket
import time
from pathlib import Path
from uuid import uuid4

import uvicorn

from vault_unified.sharing.protocol import encode, encrypt, new_identity, signed_request
from vault_unified.sharing.service import create_app

app = create_app(database=Path.cwd() / "generated-sharing.db", admin_token=os.environ["UI_TEST_BOOTSTRAP_SECRET"])
sid, key, cap = uuid4().hex, secrets.token_bytes(32), encode(secrets.token_bytes(32))
expires = int(time.time()) + 600
plain = {"version": 1, "id": sid, "title": "Generated shared account", "expires": expires,
         "fields": {"username": "generated-member", "password": os.environ["UI_TEST_ENTRY_PASSWORD"], "notes": "<script>unsafeMarkup()</script>"}}
payload = {"id": sid, "capability": cap, "blob": encrypt(key, plain, "vault-unified:share:v1:" + sid), "expires": expires, "max_reads": 1}
app.state.store.share_create(signed_request(new_identity(), "/v1/shares", payload), "/v1/shares")
sock = socket.socket(); sock.bind(("127.0.0.1", 0)); sock.listen()
port = sock.getsockname()[1]
print(json.dumps({"port": port, "seed_url": f"http://127.0.0.1:{port}/s/{sid}#key={encode(key)}&cap={cap}"}), flush=True)
uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False, proxy_headers=False)).run(sockets=[sock])

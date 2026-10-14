"""Generated-data HTTP verification against an explicitly selected service."""
import argparse
import json
import secrets
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

from vault_unified.sharing.protocol import decrypt, encode, encrypt, new_identity, signed_request

parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://127.0.0.1:8788")
parser.add_argument("--admin-token-file", type=Path, default=Path("/run/secrets/sharing_admin"))
args = parser.parse_args()
admin = args.admin_token_file.read_text().strip()
identity, sid, key, capability = new_identity(), uuid4().hex, secrets.token_bytes(32), encode(secrets.token_bytes(32))
value = secrets.token_urlsafe(32)
expires = int(time.time()) + 120
blob = encrypt(key, {"version": 1, "id": sid, "expires": expires, "title": "Generated container check", "fields": {"password": value}}, "vault-unified:share:v1:" + sid)
def post(path, body, *, signed=True, creation=False):
    payload = signed_request(identity, path, body) if signed else body
    headers = {"Content-Type": "application/json"}
    if creation: headers["Authorization"] = "Bearer " + admin
    request = Request(args.url + path, data=json.dumps(payload).encode(), headers=headers, method="POST")
    try:
        with urlopen(request, timeout=10) as response: return response.status, json.load(response)
    except HTTPError as error:
        status = error.code; error.close(); return status, {}

status, _ = post("/v1/shares", {"id": sid, "capability": capability, "blob": blob, "expires": expires, "max_reads": 2}, creation=True)
assert status == 200
status, result = post(f"/v1/shares/{sid}/read", {"capability": capability}, signed=False)
assert status == 200 and decrypt(key, result["blob"], "vault-unified:share:v1:" + sid)["fields"]["password"] == value
assert post(f"/v1/shares/{sid}/revoke", {})[0] == 200
assert post(f"/v1/shares/{sid}/read", {"capability": capability}, signed=False)[0] == 410
print(json.dumps({"containerHealth": True, "encryptedHttpRoundtrip": True, "revocation": True}))

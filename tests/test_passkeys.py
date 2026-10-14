import copy
import json
import secrets
from uuid import uuid4
from types import SimpleNamespace
from pathlib import Path

import pytest
from fido2.server import Fido2Server
from fido2.webauthn import AuthenticatorData

from vault_unified.passkeys import (
    NAMESPACE, PasskeyError, authenticate, combine, credentials_for, decode,
    encode, parse_request, redact, register, rp_for, set_credentials, summaries,
)
from vault_unified.models import SecretEntry
from vault_unified.local_store import LocalVault
from vault_unified.personal_sync.engine import run
from vault_unified.personal_sync.transport import FolderStore
from vault_unified.personal_sync.merge import reconcile
from vault_unified.personal_data import merge_personal_metadata, public_data
from vault_unified.duplicate_merge import prepare_merge, MERGE_FIELDS
from vault_unified.api.routes.entries import _to_out
from test_personal_sync_engine import profile


@pytest.fixture(autouse=True)
def isolated_configuration(tmp_path, monkeypatch):
    monkeypatch.setenv("VAULT_CONFIG_DIR", str(tmp_path / "generated-config"))


def ceremony(rp="example.com", origin="https://login.example.com"):
    server = Fido2Server({"id": rp, "name": "Generated RP"})
    options, state = server.register_begin(
        {"id": secrets.token_bytes(16), "name": "generated-user", "displayName": "Generated account"},
        user_verification="required", resident_key_requirement="required", extensions={"credProps": True},
    )
    request = parse_request("create", origin, dict(options)["publicKey"])
    stored, result = register(request, [], user_verified=True)
    auth = server.register_complete(state, result)
    return server, stored, auth, request, result


def assertion(server, stored, auth, origin="https://login.example.com", *, discoverable=False):
    options, state = server.authenticate_begin(None if discoverable else [auth.credential_data], user_verification="required")
    request = parse_request("get", origin, dict(options)["publicKey"])
    result = authenticate(request, stored, user_verified=True)
    assert server.authenticate_complete(state, [auth.credential_data], result) == auth.credential_data
    return request, result, state


def entry_with(stored):
    entry = SecretEntry(title="Generated Passkey", username=stored["user_name"], url="https://login.example.com")
    set_credentials(entry, [stored])
    return entry


def test_independent_rp_verifies_registration_allow_list_and_discoverable_signatures():
    server, stored, auth, request, result = ceremony()
    assert auth.flags & AuthenticatorData.FLAG.UV and auth.flags & AuthenticatorData.FLAG.BE
    assert not auth.flags & AuthenticatorData.FLAG.BS and auth.counter == 0
    assert result["clientExtensionResults"] == {"credProps": {"rk": True}}
    assert stored["private_key"] not in json.dumps(result)
    _, signed, _ = assertion(server, stored, auth)
    assertion(server, stored, auth, discoverable=True)
    assert stored["private_key"] not in json.dumps(signed)
    assert json.loads(decode(signed["response"]["clientDataJSON"]))["crossOrigin"] is False
    with pytest.raises(PasskeyError, match="desktop"):
        register(request, [], user_verified=False)


@pytest.mark.parametrize("origin,rp", [
    ("https://login.example.com", "evil.com"), ("https://example.com.evil.com", "example.com"),
    ("https://a.github.io", "github.io"), ("https://a.co.uk", "co.uk"),
    ("https://com", "com"), ("http://example.com", "example.com"),
    ("https://127.0.0.1", "127.0.0.1"), ("https://[::1]", "::1"),
    ("https://user@example.com", "example.com"), ("https://example.com/path", "example.com"),
    ("https://example.com?x=1", "example.com"), ("https://example.com.", "example.com"),
    ("https://a.unknown-example", "unknown-example"), ("https://example.com", "EXAMPLE.COM"),
])
def test_origin_and_public_private_suffix_boundaries(origin, rp):
    with pytest.raises(PasskeyError): rp_for(origin, rp)


def test_localhost_and_registered_subdomains():
    assert rp_for("http://localhost:43210", "localhost") == "localhost"
    assert rp_for("https://x.a.github.io", "a.github.io") == "a.github.io"
    assert rp_for("https://a.b.example.co.uk", "b.example.co.uk") == "b.example.co.uk"
    ceremony("localhost", "http://localhost:43210")


def test_exclusions_wrong_rp_allow_list_and_fresh_verification_are_enforced():
    server, stored, auth, _, _ = ceremony()
    options, _ = server.register_begin({"id": secrets.token_bytes(16), "name": "generated", "displayName": "Generated"}, [auth.credential_data])
    with pytest.raises(PasskeyError, match="excluded"):
        register(parse_request("create", "https://example.com", dict(options)["publicKey"]), [stored], user_verified=True)
    options, _ = server.authenticate_begin([auth.credential_data])
    request = parse_request("get", "https://example.com", dict(options)["publicKey"])
    with pytest.raises(PasskeyError, match="desktop"): authenticate(request, stored, user_verified=False)
    wrong = {**stored, "id": encode(secrets.token_bytes(32))}
    with pytest.raises(PasskeyError, match="match"): authenticate(request, wrong, user_verified=True)
    wrong = {**stored, "rp_id": "other.example.com"}
    with pytest.raises(PasskeyError, match="match"): authenticate(request, wrong, user_verified=True)


def test_rp_rejects_replay_tampered_origin_challenge_signature_and_uv():
    server, stored, auth, _, _ = ceremony()
    _, signed, state = assertion(server, stored, auth)
    _, fresh = server.authenticate_begin([auth.credential_data], user_verification="required")
    with pytest.raises(ValueError): server.authenticate_complete(fresh, [auth.credential_data], signed)
    for field, value in (("origin", "https://evil.example.net"), ("challenge", encode(secrets.token_bytes(32)))):
        tampered = copy.deepcopy(signed)
        client = json.loads(decode(tampered["response"]["clientDataJSON"]))
        client[field] = value
        tampered["response"]["clientDataJSON"] = encode(json.dumps(client).encode())
        with pytest.raises(ValueError): server.authenticate_complete(state, [auth.credential_data], tampered)
    tampered = copy.deepcopy(signed)
    raw = bytearray(decode(tampered["response"]["authenticatorData"]))
    raw[32] &= ~int(AuthenticatorData.FLAG.UV)
    tampered["response"]["authenticatorData"] = encode(raw)
    with pytest.raises(ValueError): server.authenticate_complete(state, [auth.credential_data], tampered)
    tampered = copy.deepcopy(signed)
    raw = bytearray(decode(tampered["response"]["signature"]))
    raw[-1] ^= 1
    tampered["response"]["signature"] = encode(raw)
    with pytest.raises(Exception): server.authenticate_complete(state, [auth.credential_data], tampered)


@pytest.mark.parametrize("change", [
    {"challenge": "!"}, {"challenge": "A"}, {"challenge": encode(b"generated") + "="},
    {"timeout": 0}, {"timeout": float("nan")}, {"timeout": True},
    {"authenticatorSelection": {"authenticatorAttachment": []}}, {"extensions": []},
    {"pubKeyCredParams": [{"alg": -257, "type": "public-key"}]},
    {"extensions": {"appid": "https://example.com"}},
    {"authenticatorSelection": {"authenticatorAttachment": "cross-platform"}},
    {"user": {"id": encode(secrets.token_bytes(65)), "name": "generated", "displayName": "Generated"}},
])
def test_unsupported_requests_do_not_generate_credentials(change):
    options = {"challenge": encode(secrets.token_bytes(32)), "rp": {"id": "example.com", "name": "Generated"},
               "user": {"id": encode(secrets.token_bytes(16)), "name": "generated", "displayName": "Generated"},
               "pubKeyCredParams": [{"alg": -7, "type": "public-key"}]}
    with pytest.raises(PasskeyError): parse_request("create", "https://example.com", {**options, **change})


def test_private_keys_survive_encrypted_restart_and_two_device_sync_only(tmp_path):
    server, stored, auth, _, _ = ceremony()
    space, key = uuid4().hex, secrets.token_bytes(32)
    a, b = profile(tmp_path / "a", space), profile(tmp_path / "b", space)
    entry = entry_with(stored); a.add(entry)
    assert stored["private_key"].encode() not in a.vault_path.read_bytes()
    a = LocalVault(a.vault_path, a.credential)
    store = FolderStore(tmp_path, space, create=True)
    run(a, store, key); run(b, store, key)
    recovered = credentials_for(b.get(entry.id))[0]
    assert recovered == stored
    assertion(server, recovered, auth)
    for path in store.root.iterdir(): assert stored["private_key"].encode() not in path.read_bytes()
    for reveal in (True, False):
        assert stored["private_key"] not in _to_out(entry, reveal=reveal).model_dump_json()
        assert stored["private_key"] not in json.dumps(public_data(entry, reveal=reveal))
        assert stored["private_key"] not in json.dumps(redact({"source_metadata": entry.source_metadata}))
    assert summaries(entry)[0]["id"] == stored["id"]


def test_duplicate_merge_preserves_both_keys_and_legacy_refresh_keeps_local_keys():
    from vault_unified.sync.conflicts import apply_resolution
    _, first, _, _, _ = ceremony(); _, second, _, _, _ = ceremony()
    target, source = entry_with(first), entry_with(second)
    merged, archived = prepare_merge(target, source, {field: "target" for field in MERGE_FIELDS})
    assert {c["id"] for c in credentials_for(merged)} == {first["id"], second["id"]}
    assert credentials_for(archived) == [second]
    assert merge_personal_metadata(target.source_metadata, {"remote": "generated"})[NAMESPACE] == target.source_metadata[NAMESPACE]
    assert NAMESPACE not in merge_personal_metadata({}, source.source_metadata)
    assert credentials_for(apply_resolution(copy.deepcopy(target), SecretEntry(title="Generated remote"), "remote")) == [first]
    assert credentials_for(apply_resolution(copy.deepcopy(target), source, "merge", SecretEntry(title="Generated chosen fields"))) == [first]
    with pytest.raises(PasskeyError, match="collision"): combine([first], [{**first, "private_key": second["private_key"]}])


def test_concurrent_credential_additions_and_deletions_do_not_resurrect_keys():
    _, first, _, _, _ = ceremony(); _, second, _, _, _ = ceremony(); _, third, _, _, _ = ceremony()
    base = entry_with(first).to_dict()
    left, right = copy.deepcopy(base), copy.deepcopy(base)
    left["source_metadata"][NAMESPACE]["credentials"] = [first, second]
    right["source_metadata"][NAMESPACE]["credentials"] = [first, third]
    result = reconcile(base, left, right)
    assert not result.conflicts and len(result.value["source_metadata"][NAMESPACE]["credentials"]) == 3
    left["source_metadata"][NAMESPACE]["credentials"] = [second]
    result = reconcile(base, left, right)
    assert not result.conflicts
    assert {item["id"] for item in result.value["source_metadata"][NAMESPACE]["credentials"]} == {second["id"], third["id"]}
    right["source_metadata"][NAMESPACE]["credentials"] = [{**first, "private_key": third["private_key"]}]
    assert reconcile(base, left, right).conflicts


def test_invalid_credentials_fail_before_atomic_write(tmp_path):
    _, stored, _, _, _ = ceremony()
    local = profile(tmp_path / "a", uuid4().hex)
    entry = entry_with(stored)
    original = local.vault_path.read_bytes()
    entry.source_metadata[NAMESPACE]["credentials"][0]["private_key"] = encode(b"generated invalid key")
    with pytest.raises(PasskeyError): local.add(entry)
    assert local.vault_path.read_bytes() == original and local.list_entries() == []
    old = LocalVault(tmp_path / "legacy.vault", secrets.token_hex(24))
    with pytest.raises(PasskeyError, match="Upgrade"): old.add(entry_with(stored))


def test_encrypted_backup_and_recovery_under_new_password_preserve_rp_credentials(tmp_path):
    from vault_unified.backup_manager import create_manual_backup
    from vault_unified.recovery_kit import create_recovery_kit, generate_recovery_code, restore_from_recovery_kit
    from vault_unified.recovery_rehearsal import rehearse_recovery
    from vault_unified.transfer import export_transfer
    from vault_unified.organization import prepare_action, is_fillable
    server, stored, auth, _, _ = ceremony()
    local = profile(tmp_path / "a", uuid4().hex)
    entry = local.add(entry_with(stored))
    backup = create_manual_backup(local.vault_path, local.credential, tmp_path / "backups")
    assert credentials_for(LocalVault(Path(backup.path), local.credential).get(entry.id)) == [stored]
    wrapper = SimpleNamespace(local=local)
    code = generate_recovery_code()
    kit = create_recovery_kit(wrapper, code, tmp_path / "kit")
    assert rehearse_recovery(kit, code)["counts"]["entries"] == 1
    target = tmp_path / "restored.vault"; password = secrets.token_hex(24)
    restore_from_recovery_kit(target, kit, code, password)
    assertion(server, credentials_for(LocalVault(target, password).get(entry.id))[0], auth)
    for format_name in ("json", "csv"):
        assert stored["private_key"] not in export_transfer(wrapper, format_name)[0]
    trashed = prepare_action(entry, "trash", tags=[])
    assert not is_fillable(trashed) and credentials_for(trashed) == [stored]
    assert credentials_for(prepare_action(trashed, "restore", tags=[])) == [stored]
    assert credentials_for(prepare_action(trashed, "purge", tags=[])) == []


def test_actual_sync_conflict_reveal_never_returns_private_keys(tmp_path):
    from test_personal_sync_connections import GeneratedKeyring, profile as connected_profile, connect
    from test_personal_sync_engine import edit
    _, first, _, _, _ = ceremony(); _, second, _, _, _ = ceremony(); _, third, _, _, _ = ceremony()
    a, am = connected_profile(tmp_path / "a", GeneratedKeyring())
    b, bm = connected_profile(tmp_path / "b", GeneratedKeyring())
    entry = a.add(entry_with(first))
    connect(a, am, tmp_path); am.synchronize(a)
    connect(b, bm, tmp_path, code=am.code(a)); bm.synchronize(b); am.synchronize(a)
    for local, replacement in ((a, second), (b, third)):
        candidate = copy.deepcopy(local.get(entry.id))
        set_credentials(candidate, [{**first, "private_key": replacement["private_key"]}])
        edit(local, entry.id, source_metadata=candidate.source_metadata)
    am.synchronize(a); bm.synchronize(b); am.synchronize(a)
    for manager, local in ((am, a), (bm, b)):
        result = manager.conflicts(local, reveal=True)
        assert result["items"]
        serialized = json.dumps(result)
        assert all(item["private_key"] not in serialized for item in (first, second, third))
        assert "private_key" not in serialized
        assert "generated-user" in serialized

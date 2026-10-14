import copy
import secrets
from uuid import uuid4

import pytest

from vault_unified.models import SecretEntry
from vault_unified.personal_data import data_for, update_data, all_history
from vault_unified.organization import ORGANIZATION_KEY
from vault_unified.personal_sync.codec import ProtocolError, seal, unseal, filename
from vault_unified.personal_sync.merge import reconcile, choose


def sample():
    return SecretEntry(title="Generated", password=secrets.token_hex(20), notes="Generated original").to_dict()


def test_two_offline_nonoverlapping_edits_converge_and_preserve_unknown_data():
    base = sample()
    base["source_metadata"] = {"generated:opaque": {"binary": secrets.token_hex(20)}}
    left, right = copy.deepcopy(base), copy.deepcopy(base)
    left["password"] = secrets.token_hex(20)
    right["notes"] = "Generated offline note"
    a, b = reconcile(base, left, right), reconcile(base, right, left)
    assert not a.conflicts and not b.conflicts and a.value == b.value
    assert a.value["password"] == left["password"] and a.value["notes"] == right["notes"]
    assert a.value["source_metadata"] == base["source_metadata"]
    assert base["notes"] == "Generated original"


def test_same_field_conflict_preserves_three_values_and_explicit_choice():
    base = sample(); left, right = copy.deepcopy(base), copy.deepcopy(base)
    left["password"], right["password"] = secrets.token_hex(20), secrets.token_hex(20)
    left["notes"] = "Generated retained note"
    result = reconcile(base, left, right)
    assert len(result.conflicts) == 1 and result.conflicts[0]["path"] == ["password"]
    assert result.conflicts[0]["base"]["value"] == base["password"]
    selected = choose(result.value, result.conflicts[0], "remote")
    assert selected["password"] == right["password"] and selected["notes"] == left["notes"]
    assert result.value["password"] == left["password"]


@pytest.mark.parametrize("deletion", ["trash", "permanent"])
def test_delete_edit_conflict_never_automatically_revives_or_discards_an_offline_edit(deletion):
    base = sample(); edited = copy.deepcopy(base); edited["notes"] = "Generated later offline edit"
    removed = None if deletion == "permanent" else {**base, "source_metadata": {ORGANIZATION_KEY: {"state": "trash"}}}
    for current, incoming in [(edited, removed), (removed, edited)]:
        result = reconcile(base, current, incoming)
        assert len(result.conflicts) == 1 and result.conflicts[0]["kind"] == "delete"
        assert result.value == current
        assert choose(result.value, result.conflicts[0], "remote") == incoming


def test_nested_fields_merge_but_deleted_fields_keep_their_conflict_presence():
    base = {"custom": {"one": "generated first", "two": "generated second"}}
    left = {"custom": {"two": "generated second"}}
    right = {"custom": {"one": "generated changed", "two": "generated second"}}
    result = reconcile(base, left, right, entry=False)
    assert result.conflicts[0]["local"] == {"present": False}
    assert choose(result.value, result.conflicts[0], "remote") == right


def test_concurrent_history_versions_survive_the_ordinary_rolling_limit():
    entry = SecretEntry(title="Generated history")
    update_data(entry, totp_secret="JBSWY3DPEHPK3PXP")
    base = entry.to_dict(); left, right = copy.deepcopy(base), copy.deepcopy(base)
    namespace = "vault_unified:personal"
    for target, prefix in [(left, "a"), (right, "b")]:
        target["source_metadata"][namespace]["history"] = [
            {"id": f"{prefix}{index}", "saved_at": f"2026-10-14T01:{index:02d}:00+00:00", "snapshot": {"notes": f"generated {prefix}{index}"}}
            for index in range(20)
        ]
    a, b = reconcile(base, left, right), reconcile(base, right, left)
    assert not a.conflicts and a.value == b.value
    restored = SecretEntry.from_dict(a.value)
    assert len(data_for(restored)["history"]) == 20 and len(all_history(restored)) == 40


def record():
    space, device = uuid4().hex, uuid4().hex
    after = sample()
    value = {"version": 1, "space": space, "device": device, "sequence": 1, "context": {},
             "object": "entry/" + after["id"], "before": None, "after": after, "resolution": False}
    return space, device, value


def test_ciphertext_hides_values_and_binds_record_identity_and_space():
    space, device, value = record(); key = secrets.token_bytes(32)
    name, encrypted = seal(key, space, value)
    assert value["after"]["password"].encode() not in encrypted
    assert unseal(key, space, name, encrypted) == value
    candidates = [(secrets.token_bytes(32), space, name, encrypted), (key, uuid4().hex, name, encrypted),
                  (key, space, filename(device, 2), encrypted), (key, space, name, encrypted[:-1] + bytes([encrypted[-1] ^ 1]))]
    for args in candidates:
        with pytest.raises(ProtocolError): unseal(*args)


@pytest.mark.parametrize("mutation", ["future", "gap", "boolean", "infinite", "unsafe-name"])
def test_invalid_record_versions_sequences_and_values_are_refused(mutation):
    space, device, value = record()
    if mutation == "future": value["version"] = 2
    if mutation == "gap": value["sequence"] = 2
    if mutation == "boolean": value["sequence"] = True
    if mutation == "infinite": value["after"]["generated"] = float("inf")
    if mutation == "unsafe-name": value["device"] = "../" + device
    with pytest.raises(ProtocolError): seal(secrets.token_bytes(32), space, value)

import base64
import copy
import secrets
from uuid import uuid4

import pytest

from vault_unified.models import SecretEntry
from vault_unified.personal_sync.codec import ProtocolError, unseal
from vault_unified.personal_sync.merge import choose
from vault_unified.personal_sync.replica import initial, queue, receive, pending_deletions


class Peer:
    def __init__(self, space, key, storage):
        self.state = initial(space, uuid4().hex)
        self.view = {}
        self.key, self.storage = key, storage

    def prepare(self, *, resolved=None):
        self.state = queue(self.state, self.view, self.key, "Generated device", resolved=resolved)

    def upload(self):
        for name, item in self.state["outbox"].items():
            encrypted = base64.b64decode(item["ciphertext"])
            assert self.storage.get(name, encrypted) == encrypted
            self.storage[name] = encrypted

    def download(self, subset=None):
        records = {name: unseal(self.key, self.state["space"], name, value) for name, value in (self.storage if subset is None else subset).items()}
        self.state, self.view, waiting = receive(self.state, self.view, records)
        return waiting

    def sync(self):
        self.prepare(); self.upload(); return self.download()


def pair():
    space, key, storage = uuid4().hex, secrets.token_bytes(32), {}
    a, b = Peer(space, key, storage), Peer(space, key, storage)
    entry = SecretEntry(title="Generated replica", password=secrets.token_hex(20)).to_dict()
    object_id = "entry/" + entry["id"]
    a.view[object_id] = entry
    a.sync(); b.sync(); a.sync(); b.sync()
    return a, b, object_id


def test_independent_profiles_merge_offline_fields_and_retry_lost_ack_idempotently():
    a, b, object_id = pair()
    a.view[object_id]["password"] = secrets.token_hex(20)
    b.view[object_id]["notes"] = "Generated offline note"
    a.prepare(); ciphertexts = copy.deepcopy(a.state["outbox"])
    a.upload()  # Simulate losing the server response and restarting from disk.
    a.state = copy.deepcopy(a.state)
    a.prepare(); assert a.state["outbox"] == ciphertexts
    a.upload(); a.download(); b.sync(); a.sync()
    assert a.view == b.view and not a.state["conflicts"] and not b.state["conflicts"]
    assert a.view[object_id]["notes"] == "Generated offline note"
    before = copy.deepcopy(a.state)
    a.download(); assert a.state == before


def test_explicit_keep_local_resolution_is_published_even_without_visible_value_change():
    a, b, object_id = pair()
    a.view[object_id]["password"], b.view[object_id]["password"] = secrets.token_hex(20), secrets.token_hex(20)
    a.sync(); b.sync(); a.sync()
    assert len(a.state["conflicts"]) == len(b.state["conflicts"]) == 1
    desired = a.view[object_id]["password"]
    a.prepare(resolved={object_id}); a.upload(); a.download(); b.sync(); a.sync()
    assert a.view == b.view and b.view[object_id]["password"] == desired
    assert not a.state["conflicts"] and not b.state["conflicts"]


def test_deleted_identity_survives_offline_old_create_and_waits_for_device_acknowledgement():
    a, b, object_id = pair()
    old = copy.deepcopy(b.view[object_id])
    del a.view[object_id]; a.sync()
    assert object_id not in a.view and pending_deletions(a.state) == 1
    # A newly authorized installation restores an old offline backup, with a
    # new identity and no knowledge of the deletion.
    c = Peer(a.state["space"], a.key, a.storage)
    c.view[object_id] = old; c.sync(); a.sync()
    assert object_id not in a.view
    assert any(item["kind"] == "delete" for item in a.state["conflicts"].values())
    assert object_id in a.state["tombstones"]
    b.sync(); b.sync(); c.sync(); a.sync()
    assert pending_deletions(a.state) == 0
    assert object_id in a.state["tombstones"]  # Conservative retention after ACK.


def test_missing_predecessor_waits_and_cloned_device_identity_is_refused():
    space, key, storage = uuid4().hex, secrets.token_bytes(32), {}
    a, b = Peer(space, key, storage), Peer(space, key, storage)
    entry = SecretEntry(title="Generated pending").to_dict(); object_id = "entry/" + entry["id"]
    a.view[object_id] = entry; a.prepare(); a.upload()
    names = sorted(storage)
    assert b.download({names[1]: storage[names[1]]}) == 1
    assert b.view == {} and b.state["seen"] == {}
    assert b.download() == 0 and b.view[object_id] == entry
    clone = Peer(space, key, storage); clone.state = initial(space, a.state["device"])
    with pytest.raises(ProtocolError, match="reused"): clone.download()


def test_resolution_does_not_clear_new_conflict_that_arrived_after_confirmation():
    a, b, object_id = pair()
    c = Peer(a.state["space"], a.key, a.storage); c.sync()
    a.view[object_id]["password"], b.view[object_id]["password"] = secrets.token_hex(20), secrets.token_hex(20)
    a.sync(); b.sync(); a.sync()
    a.prepare(resolved={object_id})
    c.view[object_id]["password"] = secrets.token_hex(20)
    c.sync()  # New independent edit, after a's resolution was queued.
    a.upload(); a.download()
    assert any(item["device"] == c.state["device"] for item in a.state["conflicts"].values())

import base64
import copy
import secrets
from uuid import uuid4

import pytest

from vault_unified.local_store import LocalVault, EntryTransactionConflict
from vault_unified.models import SecretEntry, SyncStatus
from vault_unified.organization import prepare_action
from vault_unified.personal_data import data_for, set_data, add_attachment, record_history
from vault_unified.personal_sync.codec import STATE_NAMESPACE, ProtocolError
from vault_unified.personal_sync.engine import run, resolve
from vault_unified.personal_sync.payload import project, materialize
from vault_unified.personal_sync.replica import initial
from vault_unified.personal_sync.transport import FolderStore, StorageUnavailable, WebDAVStore
from vault_unified.v3_crypto import create_v3_file
from test_personal_sync_transport import generated_webdav


def profile(directory, space):
    directory.mkdir()
    password = secrets.token_hex(24)
    state = initial(space, uuid4().hex)
    state["connection"] = {"label": "Generated computer"}
    path = directory / "generated.vault"
    create_v3_file(path, password, {"version": 3, "entries": {}, "metadata": {STATE_NAMESPACE: state}})
    return LocalVault(path, password)


def state(local): return local.metadata_value(STATE_NAMESPACE)


def edit(local, entry_id, **fields):
    prior = local.get(entry_id)
    candidate = copy.deepcopy(prior)
    for key, value in fields.items(): setattr(candidate, key, value)
    candidate.mark_dirty()
    local.commit_entry(candidate, create=False, expected_updated_at=prior.updated_at)


def test_real_encrypted_vaults_folder_sync_personal_content_and_offline_fields(tmp_path):
    space, key = uuid4().hex, secrets.token_bytes(32)
    a, b = profile(tmp_path / "a", space), profile(tmp_path / "b", space)
    store = FolderStore(tmp_path, space, create=True)
    entry = SecretEntry(title="Generated complete account", password=secrets.token_hex(24))
    value = data_for(entry); value["totp_secret"] = base64.b32encode(secrets.token_bytes(20)).decode()
    set_data(entry, value)
    add_attachment(entry, filename="generated.txt", mime_type="text/plain", data_b64=base64.b64encode(b"Generated attachment").decode())
    record_history(entry)
    a.add(entry)
    a.update_metadata("generated:future", lambda _: {"field": "Preserved future extension"})
    run(a, store, key); run(b, store, key); run(a, store, key)
    assert project(a.export_payload()) == project(b.export_payload())
    assert data_for(b.get(entry.id))["attachments"][0]["data_b64"] == base64.b64encode(b"Generated attachment").decode()
    edit(a, entry.id, password=secrets.token_hex(24))
    edit(b, entry.id, notes="Generated offline note")
    run(a, store, key); run(b, store, key); run(a, store, key)
    assert project(a.export_payload()) == project(b.export_payload()) and not state(a)["conflicts"]
    reopened = LocalVault(b.vault_path, b.credential)
    assert reopened.export_payload() == b.export_payload()
    for path in store.root.iterdir():
        assert b"Generated complete account" not in path.read_bytes()
        assert STATE_NAMESPACE.encode() not in path.read_bytes()


def test_lost_upload_ack_restart_and_further_offline_edit_preserve_outbox(tmp_path):
    space, key = uuid4().hex, secrets.token_bytes(32)
    a = profile(tmp_path / "a", space); store = FolderStore(tmp_path, space, create=True)
    entry = a.add(SecretEntry(title="Generated retry", password=secrets.token_hex(20)))
    class LostAck:
        def put(self, name, blob): store.put(name, blob); raise StorageUnavailable("Generated lost acknowledgement")
    with pytest.raises(StorageUnavailable): run(a, LostAck(), key)
    outbox = state(a)["outbox"]
    a = LocalVault(a.vault_path, a.credential)
    assert state(a)["outbox"] == outbox
    edit(a, entry.id, notes="Generated additional offline edit")
    run(a, store, key)
    for name, item in outbox.items(): assert store.get(name) == base64.b64decode(item["ciphertext"])
    b = profile(tmp_path / "b", space); run(b, store, key)
    assert b.get(entry.id).notes == "Generated additional offline edit" and not state(a)["outbox"]


def test_edit_between_durable_queue_and_network_response_cannot_be_overwritten(tmp_path):
    space, key = uuid4().hex, secrets.token_bytes(32)
    a = profile(tmp_path / "a", space); store = FolderStore(tmp_path, space, create=True)
    entry = a.add(SecretEntry(title="Generated race"))
    class EditingStore:
        edited = False
        def put(self, name, blob):
            store.put(name, blob)
            if not self.edited:
                self.edited = True
                edit(a, entry.id, notes="Generated edit during request")
        def list(self): return store.list()
        def get(self, name): return store.get(name)
    with pytest.raises(EntryTransactionConflict): run(a, EditingStore(), key)
    assert a.get(entry.id).notes == "Generated edit during request" and state(a)["outbox"]
    run(a, store, key)
    b = profile(tmp_path / "b", space); run(b, store, key)
    assert b.get(entry.id).notes == "Generated edit during request"


def test_actual_webdav_delete_conflict_review_staleness_and_explicit_choice(tmp_path):
    space, key = uuid4().hex, secrets.token_bytes(32)
    a, b = profile(tmp_path / "a", space), profile(tmp_path / "b", space)
    with generated_webdav() as (address, _):
        store = WebDAVStore(address, space, "generated", secrets.token_hex(20), create=True)
        entry = a.add(SecretEntry(title="Generated deletion conflict", password=secrets.token_hex(20)))
        run(a, store, key); run(b, store, key); run(a, store, key)
        candidate = prepare_action(a.get(entry.id), "trash", tags=[])
        a.commit_entry(candidate, create=False, expected_updated_at=a.get(entry.id).updated_at)
        edit(b, entry.id, notes="Generated concurrent note")
        run(a, store, key); run(b, store, key); run(a, store, key)
        choices = {key: "local" for key in state(b)["conflicts"]}
        assert choices and any(item["kind"] == "delete" for item in state(b)["conflicts"].values())
        generation = b.generation
        edit(b, entry.id, notes="Generated newer note before review")
        with pytest.raises(EntryTransactionConflict): resolve(b, key, choices, expected_generation=generation)
        resolve(b, key, choices, expected_generation=b.generation)
        run(b, store, key); run(a, store, key)
        assert not state(a)["conflicts"] and not state(b)["conflicts"]
        assert a.get(entry.id).notes == "Generated newer note before review"
        # Permanent remote removal retains the old connector tombstone locally.
        for action in ("trash", "purge"):
            candidate = prepare_action(b.get(entry.id), action, tags=[])
            b.commit_entry(candidate, create=False, expected_updated_at=b.get(entry.id).updated_at)
        run(b, store, key); run(a, store, key)
        assert a.get(entry.id).sync_status == SyncStatus.DELETED_PENDING
        assert not a.get(entry.id).password and "entry/" + entry.id in state(a)["tombstones"]


def test_incoming_unknown_or_malformed_entry_fields_refuse_without_loss(tmp_path):
    local = profile(tmp_path / "a", uuid4().hex)
    local.add(SecretEntry(title="Generated stable entry"))
    before = local.export_payload(); view = project(before)
    object_id = next(iter(view))
    for field, value in [("password", {"unexpected": True}), ("future_unknown_field", "retained or refused"), ("sync_ledger", {})]:
        candidate = copy.deepcopy(view); candidate[object_id][field] = value
        with pytest.raises(ProtocolError): materialize(before, candidate, state(local))
    assert local.export_payload() == before

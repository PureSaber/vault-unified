"""Causal histories must make progress within bounded download pages."""
import base64
import secrets
from uuid import uuid4

import pytest

from vault_unified.personal_sync import engine
from vault_unified.personal_sync.codec import ProtocolError, filename, seal
from vault_unified.personal_sync.connections import encode_key
from vault_unified.personal_sync.payload import project
from vault_unified.personal_sync.replica import initial, queue, receive
from vault_unified.personal_sync.transport import FolderStore
from test_personal_sync_connections import GeneratedKeyring, profile, options
from test_personal_sync_engine import profile as connected_profile


@pytest.fixture(autouse=True)
def isolated_backup_catalog(tmp_path, monkeypatch):
    monkeypatch.setenv("VAULT_CONFIG_DIR", str(tmp_path / "generated-config"))


def causal_history(tmp_path, limit):
    space, key = uuid4().hex, secrets.token_bytes(32)
    store = FolderStore(tmp_path, space, create=True)
    # B's low sequence numbers all depend on A's much higher sequence.
    a = initial(space, "a" * 32)
    b = initial(space, "b" * 32)
    first = {f"metadata/generated:a{i}": {"data": {"value": i}} for i in range(2 * limit - 1)}
    a = queue(a, first, key, "Generated A")
    records = {name: item["record"] for name, item in a["outbox"].items()}
    # Seed immutable, authenticated history directly; upload durability has its
    # own transport tests and fsync thousands of fixture files is costly.
    for name, item in a["outbox"].items(): (store.root / name).write_bytes(base64.b64decode(item["ciphertext"]))
    b, view, waiting = receive(b, {}, records)
    assert waiting == 0
    view.update({f"metadata/generated:b{i}": {"data": {"value": i}} for i in range(limit)})
    b = queue(b, view, key, "Generated B")
    for name, item in b["outbox"].items(): (store.root / name).write_bytes(base64.b64decode(item["ciphertext"]))
    return store, space, key, view


def test_default_download_limit_progresses_past_a_thousand_blocked_changes(tmp_path):
    limit = engine.MAX_DOWNLOAD_RECORDS
    assert limit == 1000
    store, space, key, expected = causal_history(tmp_path, limit)
    state, view = initial(space, uuid4().hex), {}
    for _ in range(8):
        previous = dict(state["seen"])
        records, more = engine.download(store, state, key, lambda: None)
        assert len(records) <= limit
        state, view, waiting = receive(state, view, records)
        assert state["seen"] != previous, "A valid history must progress on every nonempty page"
        if not more and not waiting: break
    assert view == expected


@pytest.mark.parametrize("mode", ["run", "join"])
def test_real_vault_run_and_join_complete_causally_ordered_pages(tmp_path, monkeypatch, mode):
    monkeypatch.setattr(engine, "MAX_DOWNLOAD_RECORDS", 8)
    store, space, key, expected = causal_history(tmp_path, 8)
    if mode == "run":
        local = connected_profile(tmp_path / "running", space)
        for _ in range(8):
            result = engine.run(local, store, key)
            if not result["more"] and not result["waiting"]: break
        assert project(local.export_payload()) == expected
        return

    joining, manager = profile(tmp_path / "joining", GeneratedKeyring())
    before = joining.vault_path.read_bytes()
    preview = manager.preview(joining, "generated", options(tmp_path, code="VUS1." + space + "." + encode_key(key)))
    assert joining.vault_path.read_bytes() == before
    manager.apply(joining, "generated", preview["preview_token"])
    assert project(joining.export_payload()) == expected


@pytest.mark.parametrize("damage", ["missing", "tampered"])
def test_join_refuses_missing_or_tampered_causal_predecessor(tmp_path, monkeypatch, damage):
    monkeypatch.setattr(engine, "MAX_DOWNLOAD_RECORDS", 8)
    store, space, key, _ = causal_history(tmp_path, 8)
    path = store.root / filename("a" * 32, 12)
    if damage == "missing": path.unlink()
    else: path.write_bytes(path.read_bytes()[:-1] + bytes([path.read_bytes()[-1] ^ 1]))
    joining, manager = profile(tmp_path / "joining", GeneratedKeyring())
    before = joining.vault_path.read_bytes()
    with pytest.raises(ProtocolError):
        manager.preview(joining, "generated", options(tmp_path, code="VUS1." + space + "." + encode_key(key)))
    assert joining.vault_path.read_bytes() == before


@pytest.mark.parametrize("budget", ["records", "bytes"])
def test_dependency_probes_obey_page_budgets_and_still_progress(tmp_path, monkeypatch, budget):
    store, space, key, expected = causal_history(tmp_path, 4)
    largest = max(len(store.get(name)) for name in store.list())
    monkeypatch.setattr(engine, "MAX_DOWNLOAD_RECORDS", 4 if budget == "records" else 1000)
    monkeypatch.setattr(engine, "MAX_DOWNLOAD_BYTES", largest * 4)
    class CountedStore:
        def list(self): return store.list()
        def get(self, name):
            blob = store.get(name)
            fetched.append(len(blob))
            return blob
    state, view = initial(space, uuid4().hex), {}
    for _ in range(12):
        fetched = []
        records, more = engine.download(CountedStore(), state, key, lambda: None)
        assert len(fetched) <= engine.MAX_DOWNLOAD_RECORDS
        # A size check needs one bounded blob read; it is not retained if over.
        assert sum(fetched) <= engine.MAX_DOWNLOAD_BYTES + largest
        assert sum(len(store.get(name)) for name in records) <= engine.MAX_DOWNLOAD_BYTES
        previous = state["seen"]
        state, view, waiting = receive(state, view, records)
        assert state["seen"] != previous
        if not more and not waiting: break
    assert view == expected


@pytest.mark.parametrize("limit", ["records", "bytes", "cycle"])
def test_causal_dependency_resource_exhaustion_and_cycles_fail_closed(tmp_path, monkeypatch, limit):
    space, key = uuid4().hex, secrets.token_bytes(32)
    store = FolderStore(tmp_path, space, create=True)
    devices = [char * 32 for char in "abcd"]
    for i, device in enumerate(devices):
        context = {device: 0}
        if i < 3: context[devices[i + 1]] = 1
        elif limit == "cycle": context[devices[0]] = 1
        record = {"version": 1, "space": space, "device": device, "sequence": 1,
                  "context": context, "object": "device/" + device, "before": None,
                  "after": {"label": "Generated", "sequence": 1}, "resolution": False}
        name, blob = seal(key, space, record)
        (store.root / name).write_bytes(blob)
    monkeypatch.setattr(engine, "MAX_DOWNLOAD_RECORDS", 3 if limit == "records" else 4)
    if limit == "bytes":
        monkeypatch.setattr(engine, "MAX_DOWNLOAD_BYTES", max(len(store.get(name)) for name in store.list()) * 2)
    with pytest.raises(ProtocolError, match="causal cycle" if limit == "cycle" else "resource limit"):
        engine.download(store, initial(space, uuid4().hex), key, lambda: None)


def test_causal_download_honors_cancellation_between_fetches(tmp_path):
    store, space, key, _ = causal_history(tmp_path, 4)
    calls = 0
    def check():
        nonlocal calls
        calls += 1
        if calls == 3: raise PermissionError("Generated locked session")
    with pytest.raises(PermissionError, match="locked session"):
        engine.download(store, initial(space, uuid4().hex), key, check)
    assert calls == 3

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4
import hashlib
import json
import secrets
from urllib.error import HTTPError

import pytest

from test_system_session_lock import runtime
from vault_unified import password_health as health
from vault_unified.models import SecretEntry
from vault_unified.organization import ORGANIZATION_KEY
from vault_unified.session import sessions


def populate(auth):
    vault = sessions.get(auth["Authorization"].split()[1])
    weak = "generated111"
    strong = secrets.token_urlsafe(24)
    a = vault.add("Generated first", "generated", weak, "https://account.example.test/path?private=discard", auto_push=False)
    b = vault.add("Generated second", "generated", weak, auto_push=False)
    vault.add("Generated strong", "generated", strong, auto_push=False)
    vault.add("Generated long", "generated", secrets.token_hex(50), auto_push=False)
    vault.local.add(SecretEntry(title="Generated archived", password=weak, source_metadata={ORGANIZATION_KEY: {"state": "archived"}}))
    return vault, a, b, weak, strong


def test_local_review_is_offline_has_no_secret_or_hash_and_does_not_write(runtime, monkeypatch):
    _, client, _, auth, _ = runtime
    vault, first, second, weak, strong = populate(auth)
    monkeypatch.setattr(health, "fetch_range", lambda _: pytest.fail("Offline review must not call the network"))
    before = vault.vault_path.read_bytes()
    response = client.get("/api/security/password-health", headers=auth)
    assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
    result = response.json()
    assert result["total"] == 4 and result["reused"] == 2 and result["unscored"] == 1
    assert result["weak"] >= 2
    entry = next(item for item in result["entries"] if item["id"] == first.id)
    assert entry["change_url"] == "https://account.example.test/.well-known/change-password"
    assert entry["reuse_count"] == 2
    for value in (weak, strong, hashlib.sha1(weak.encode()).hexdigest()):
        assert value not in response.text
    assert vault.vault_path.read_bytes() == before


def test_exposure_requires_explicit_consent_and_shares_reuse_result(runtime, monkeypatch):
    _, client, _, auth, _ = runtime
    vault, first, second, weak, _ = populate(auth)
    digest = hashlib.sha1(weak.encode()).hexdigest().upper()
    calls = []
    def network(prefix):
        calls.append(prefix)
        return f"{'0' * 35}:0\r\n{digest[5:]}:17\r\n"
    monkeypatch.setattr(health, "fetch_range", network)
    path = "/api/security/exposure"
    for body in [{"entry_id": first.id}, {"entry_id": first.id, "confirm_network": False}, {"entry_id": first.id, "confirm_network": "true"}]:
        assert client.post(path, headers=auth, json=body).status_code in (400, 422)
    assert not calls
    before = vault.vault_path.read_bytes()
    response = client.post(path, headers=auth, json={"entry_id": first.id, "confirm_network": True})
    assert response.status_code == 200
    assert response.json()["count"] == 17
    assert set(response.json()["matching_entry_ids"]) == {first.id, second.id}
    assert calls == [digest[:5]] and digest not in response.text and weak not in response.text
    assert vault.vault_path.read_bytes() == before


@pytest.mark.parametrize("text", ["", "failure", "F" * 35 + ":bad", "F" * 35 + ":1234567890123"])
def test_malformed_exposure_response_is_never_reported_clean(monkeypatch, text):
    monkeypatch.setattr(health, "fetch_range", lambda _: text)
    with pytest.raises(health.ExposureUnavailable):
        health.exposure_count(secrets.token_hex(16))


def test_network_transport_is_fixed_https_padded_bounded_and_redacts_errors(monkeypatch):
    calls = []
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, limit):
            assert limit == 1_048_577
            return ("0" * 35 + ":0\r\n").encode()
    class Opener:
        def open(self, request, timeout):
            calls.append(request)
            assert request.full_url == "https://api.pwnedpasswords.com/range/ABCDE"
            assert request.get_header("Add-padding") == "true" and request.get_header("User-agent") == "Vault-Unified"
            assert timeout == 8 and request.data is None
            return Response()
    monkeypatch.setattr(health, "build_opener", lambda handler: Opener())
    assert health.fetch_range("ABCDE").endswith(":0\r\n")
    assert len(calls) == 1
    assert health.NoRedirect().redirect_request(None, None, 302, "", {}, "https://elsewhere.invalid") is None
    class Failure:
        def open(self, request, timeout):
            raise HTTPError(request.full_url, 503, "generated-secret-response", {}, None)
    monkeypatch.setattr(health, "build_opener", lambda _: Failure())
    with pytest.raises(health.ExposureUnavailable) as failed:
        health.fetch_range("ABCDE")
    assert "ABCDE" not in str(failed.value) and "generated-secret" not in str(failed.value)


@pytest.mark.parametrize("action,expected", [("edit", 409), ("lock", 401)])
def test_late_exposure_result_is_rejected_after_edit_or_lock(runtime, monkeypatch, action, expected):
    _, client, _, auth, _ = runtime
    vault, first, _, _, _ = populate(auth)
    started, release = Event(), Event()
    def network(_):
        started.set(); assert release.wait(5)
        return "0" * 35 + ":0\r\n"
    monkeypatch.setattr(health, "fetch_range", network)
    with ThreadPoolExecutor() as pool:
        future = pool.submit(client.post, "/api/security/exposure", headers=auth, json={"entry_id": first.id, "confirm_network": True})
        assert started.wait(5)
        try:
            if action == "edit": vault.local.update(first.id, password=secrets.token_hex(20))
            else: sessions.lock_all()
        finally: release.set()
        assert future.result(timeout=5).status_code == expected


def test_change_links_reject_non_web_schemes_and_strip_private_paths():
    for url in ["javascript:alert(1)", "file:///C:/generated", "http://example.test", "https://user:pass@example.test"]:
        assert health.change_url(url) == ""
    assert health.change_url("https://EXAMPLE.test:8443/private?token=generated") == "https://example.test:8443/.well-known/change-password"

from __future__ import annotations

import base64
import secrets

import pytest

from test_browser_daily_use import app
from vault_unified.organization import prepare_action
from vault_unified.personal_data import update_data
from vault_unified.session import sessions
from vault_unified.totp import TotpError, current_totp, parse_totp


# Public RFC 6238 Appendix B known-answer vectors, not user credentials.
@pytest.mark.parametrize("timestamp, expected", [
    (59, ("94287082", "46119246", "90693936")),
    (1111111109, ("07081804", "68084774", "25091201")),
    (1111111111, ("14050471", "67062674", "99943326")),
    (1234567890, ("89005924", "91819424", "93441116")),
    (2000000000, ("69279037", "90698825", "38618901")),
    (20000000000, ("65353130", "77737706", "47863826")),
])
def test_rfc6238_all_algorithms(timestamp, expected):
    for algorithm, size, code in zip(("SHA1", "SHA256", "SHA512"), (20, 32, 64), expected):
        key = base64.b32encode((b"1234567890" * 7)[:size]).decode().rstrip("=")
        uri = f"otpauth://totp/RFC?secret={key}&algorithm={algorithm}&digits=8"
        result = current_totp(uri, now=timestamp)
        assert result["code"] == code
        assert result["expires_at"] == (timestamp // 30 + 1) * 30
        assert 0 < result["remaining_seconds"] <= 30


@pytest.mark.parametrize("value", ["", "invalid key!!!", "otpauth://hotp/Generated?secret=JBSWY3DPEHPK3PXP", "otpauth://totp/Generated?secret=JBSWY3DPEHPK3PXP&secret=JBSWY3DPEHPK3PXP", "otpauth://totp/Generated?secret=JBSWY3DPEHPK3PXP&period=0", "otpauth://totp/Generated?secret=JBSWY3DPEHPK3PXP&digits=7", "otpauth://totp/Generated?secret=JBSWY3DPEHPK3PXP&algorithm=MD5"])
def test_invalid_key_errors_never_include_input(value):
    with pytest.raises(TotpError) as result:
        parse_totp(value)
    if value:
        assert value not in str(result.value)


def test_raw_key_normalization_uri_metadata_and_boundary():
    value = "jbsw y3dp ehpk 3pxp"
    assert current_totp(value, now=29.9)["code"] == current_totp("JBSWY3DPEHPK3PXP", now=29.9)["code"]
    assert current_totp(value, now=30)["code"] != current_totp(value, now=29.9)["code"]
    parsed = parse_totp("otpauth://totp/Generated%3Auser?secret=JBSWY3DPEHPK3PXP&issuer=Generated&period=45")
    assert parsed.label == "Generated:user" and parsed.issuer == "Generated" and parsed.period == 45
    assert "JBSWY" not in repr(parsed)


def test_totp_api_has_no_store_copy_expiry_and_browser_origin_lock_guards(app, monkeypatch):
    key = base64.b32encode(secrets.token_bytes(20)).decode()
    entry = app.vault.add("Generated OTP", username="generated", password="generated-password", url="https://example.invalid", auto_push=False)
    update_data(entry, totp_secret=key)
    app.vault.local.replace_entry(entry)
    monkeypatch.setattr("vault_unified.totp.time.time", lambda: 59.25)
    copied = []
    monkeypatch.setattr("vault_unified.api.routes.entries.copy_to_clipboard", lambda value, **kwargs: copied.append((value, kwargs)))
    before = app.path.read_bytes()
    preview = app.client.post("/api/entries/tools/totp/preview", headers=app.desktop, json={"value": key})
    assert preview.status_code == 200 and preview.headers["cache-control"] == "no-store"
    assert preview.json()["valid"] and key not in preview.text
    assert app.client.post("/api/entries/tools/totp/preview", headers=app.desktop, json={"value": "invalid generated key"}).json() == {"valid": False}
    result = app.client.post(f"/api/entries/{entry.id}/totp/copy", headers=app.desktop)
    assert result.status_code == 200 and result.json()["clears_in_seconds"] == 1
    assert copied == [(current_totp(key, now=59.25)["code"], {"clear_after": 1})]
    body = {"entry_id": entry.id, "url": entry.url}
    result = app.client.post("/api/browser/totp", headers=app.browser, json=body)
    assert result.status_code == 200 and result.headers["cache-control"] == "no-store"
    assert result.json()["code"] == current_totp(key, now=59.25)["code"]
    assert key not in result.text and app.path.read_bytes() == before
    for url in ("https://www.example.invalid", "https://other.invalid", "http://example.invalid", "https://example.invalid:8443"):
        assert app.client.post("/api/browser/totp", headers=app.browser, json={**body, "url": url}).status_code == 400
    assert app.client.post("/api/browser/totp", headers={**app.browser, "Origin": "chrome-extension://bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}, json=body).status_code == 401
    app.vault.local.replace_entry(prepare_action(entry, "archive", tags=[]))
    assert app.client.post("/api/browser/totp", headers=app.browser, json=body).status_code == 400
    sessions.lock_all()
    assert app.client.post("/api/browser/totp", headers=app.browser, json=body).status_code == 401

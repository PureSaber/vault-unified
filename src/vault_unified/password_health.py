"""Offline password review and explicitly requested range-only exposure lookup."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import re
from urllib.request import HTTPRedirectHandler, Request, build_opener

from zxcvbn import zxcvbn

from vault_unified.organization import is_fillable
from vault_unified.personal_data import data_for
from vault_unified.website_rules import website


class ExposureUnavailable(ValueError):
    pass


def login_entries(vault):
    return [entry for entry in vault.local.list_entries()
            if is_fillable(entry) and data_for(entry)["entry_type"] == "login" and entry.password]


def change_url(value: str) -> str:
    try:
        site = website(value)
        return site.origin + "/.well-known/change-password" if site.scheme == "https" else ""
    except ValueError:
        return ""


def report(vault) -> dict:
    entries = login_entries(vault)
    counts = Counter(entry.password for entry in entries)
    results = []
    for entry in entries:
        # Keep the upstream bound: pathological long input can take excessive CPU.
        score = int(zxcvbn(entry.password, user_inputs=[entry.username[:72], entry.title[:72]])["score"]) if len(entry.password) <= 72 else None
        weak = len(entry.password) < 12 or (score is not None and score < 3)
        results.append({"id": entry.id, "title": entry.title, "username": entry.username,
                        "updated_at": entry.updated_at, "change_url": change_url(entry.url),
                        "weak": weak, "score": score, "reused": counts[entry.password] > 1,
                        "reuse_count": counts[entry.password]})
    return {"checked_at": datetime.now(timezone.utc).isoformat(), "entries": results,
            "total": len(results), "weak": sum(item["weak"] for item in results),
            "reused": sum(item["reused"] for item in results),
            "unscored": sum(item["score"] is None for item in results)}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_range(prefix: str) -> str:
    if not re.fullmatch(r"[0-9A-F]{5}", prefix):
        raise ExposureUnavailable("Exposure check unavailable")
    request = Request("https://api.pwnedpasswords.com/range/" + prefix,
                      headers={"Add-Padding": "true", "User-Agent": "Vault-Unified", "Accept": "text/plain"})
    try:
        with build_opener(NoRedirect()).open(request, timeout=8) as response:
            if response.status != 200:
                raise ValueError()
            body = response.read(1_048_577)
            if len(body) > 1_048_576:
                raise ValueError()
            return body.decode("ascii")
    except Exception:
        # URLs/hash prefixes and response bodies must not become UI/log details.
        raise ExposureUnavailable("Exposure check unavailable") from None


def exposure_count(password: str) -> int:
    digest = hashlib.sha1(password.encode("utf-8"), usedforsecurity=False).hexdigest().upper()
    body = fetch_range(digest[:5])
    found = 0
    lines = body.splitlines()
    if not lines:
        raise ExposureUnavailable("Exposure check unavailable")
    for line in lines:
        match = re.fullmatch(r"([0-9A-Fa-f]{35}):([0-9]{1,12})", line.strip())
        if match is None:
            raise ExposureUnavailable("Exposure check unavailable")
        if match[1].upper() == digest[5:]:
            found = max(found, int(match[2]))
    return found

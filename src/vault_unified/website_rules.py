"""Explicit website matching with an offline public/private suffix snapshot."""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from urllib.parse import urlsplit

import idna
import tldextract

WEBSITE_KEY = "vault_unified:website_rules"


@dataclass(frozen=True)
class Website:
    scheme: str
    host: str
    port: int

    @property
    def origin(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        port = "" if self.port == (443 if self.scheme == "https" else 80) else f":{self.port}"
        return f"{self.scheme}://{host}{port}"


def website(value: str) -> Website:
    if not isinstance(value, str) or len(value) > 2048 or "\\" in value or any(ord(char) <= 32 or ord(char) == 127 for char in value):
        raise ValueError("Enter an HTTP or HTTPS website without whitespace or credentials")
    try:
        url = urlsplit(value)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username is not None or url.password is not None:
            raise ValueError()
        host = url.hostname
        try:
            host = ipaddress.ip_address(host).compressed
        except ValueError:
            host = idna.encode(host, uts46=True, std3_rules=True).decode("ascii").lower()
        # Trailing-dot origins stay distinct, just as the browser origin does.
        if "%" in host:
            raise ValueError()
        port = url.port if url.port is not None else (443 if url.scheme == "https" else 80)
        if not 1 <= port <= 65535:
            raise ValueError()
        return Website(url.scheme, host, port)
    except (ValueError, UnicodeError) as exc:
        raise ValueError("Enter an HTTP or HTTPS website without whitespace or credentials") from exc


@lru_cache(maxsize=1)
def suffixes():
    # No network fetches, disk cache or cache file locks during matching.
    return tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None, include_psl_private_domains=True)


def base_domain(host: str) -> str:
    try:
        ipaddress.ip_address(host)
        return ""
    except ValueError:
        pass
    if host.endswith("."):
        return ""
    return suffixes()(host).top_domain_under_public_suffix


def normalize_rules(value: Any) -> dict:
    if value is None:
        value = {}
    if not isinstance(value, dict) or set(value) - {"match", "additional_urls", "excluded_urls"}:
        raise ValueError("Website rules have an invalid shape")
    mode = value.get("match", "exact")
    if not isinstance(mode, str) or mode not in {"exact", "base_domain"}:
        raise ValueError("Choose exact host or base domain matching")
    result = {"match": mode}
    for field in ("additional_urls", "excluded_urls"):
        urls = value.get(field, [])
        if not isinstance(urls, list) or len(urls) > 20:
            raise ValueError("Use at most twenty websites per rule list")
        result[field] = list(dict.fromkeys(website(url).origin for url in urls))
    return result


def rules_for(entry: Any) -> dict:
    value = entry.source_metadata.get(WEBSITE_KEY)
    if value is None:
        return normalize_rules({})
    if not isinstance(value, dict) or set(value) != {"version", "rules"} or type(value["version"]) is not int or value["version"] != 1:
        raise ValueError("Unsupported website rules schema")
    return normalize_rules(value["rules"])


def validate_rules(primary_url: str, rules: dict) -> None:
    if rules["match"] != "base_domain":
        return
    included = ([primary_url] if primary_url else []) + rules["additional_urls"]
    if not included or any(not base_domain(website(url).host) for url in included):
        raise ValueError("Base domain matching requires a known registrable domain; use exact matching for local addresses")


def set_rules(entry: Any, value: dict) -> None:
    rules = normalize_rules(value)
    validate_rules(entry.url, rules)
    if rules == normalize_rules({}):
        entry.source_metadata.pop(WEBSITE_KEY, None)
    else:
        entry.source_metadata[WEBSITE_KEY] = {"version": 1, "rules": rules}


def matches_rules(primary_url: str, rules: dict, target: Website) -> bool:
    if target.origin in rules["excluded_urls"]:
        return False
    for value in ([primary_url] if primary_url else []) + rules["additional_urls"]:
        try:
            saved = website(value)
        except ValueError:
            continue
        if saved.scheme != target.scheme or saved.port != target.port:
            continue
        if saved.host == target.host:
            return True
        if rules["match"] == "base_domain":
            domain = base_domain(saved.host)
            if domain and domain == base_domain(target.host):
                return True
    return False


def matches_entry(entry: Any, target: Website) -> bool:
    try:
        return matches_rules(entry.url, rules_for(entry), target)
    except ValueError:
        return False


def require_website_payload(vault: Any, entries: list[Any]) -> None:
    if vault.payload_version < 3 and any(WEBSITE_KEY in entry.source_metadata for entry in entries):
        raise ValueError("Upgrade the vault in Security & recovery before saving website rules")

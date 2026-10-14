"""Portable ES256 credentials and WebAuthn wire responses.

The caller must obtain fresh, local user verification and commit a newly created
credential before releasing its response. This module does not expose an API or
make a presence/verification decision on behalf of a browser.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import ipaddress
import json
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlsplit

import idna
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fido2.cose import ES256
from fido2.webauthn import Aaguid, AttestationObject, AttestedCredentialData, AuthenticatorData, CollectedClientData

from vault_unified.website_rules import base_domain, suffixes, website

NAMESPACE = "vault_unified:passkeys"
MAX_CREDENTIALS = 100
FIELDS = {"id", "rp_id", "rp_name", "user_id", "user_name", "user_display_name", "created_at", "algorithm", "private_key"}


class PasskeyError(ValueError):
    """A sanitized protocol/storage error, safe to present without request data."""


def encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def decode(value, *, minimum=1, maximum=1024) -> bytes:
    if not isinstance(value, str) or len(value) > (maximum * 4 + 2) // 3 or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise PasskeyError("Invalid Passkey binary value")
    try:
        result = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except ValueError:
        raise PasskeyError("Invalid Passkey binary value") from None
    if not minimum <= len(result) <= maximum or encode(result) != value:
        raise PasskeyError("Invalid Passkey binary value")
    return result


def text(value, maximum=256, *, empty=False):
    if (not isinstance(value, str) or len(value) > maximum or (not empty and not value)
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise PasskeyError("Invalid Passkey text")
    return value


def rp_for(origin: str, requested=None) -> str:
    """Check effective-domain scope using the bundled public/private PSL."""
    try:
        site = website(origin)
        parsed = urlsplit(origin)
        if parsed.path or parsed.query or parsed.fragment or origin != site.origin or site.host.endswith("."):
            raise ValueError()
        if site.scheme != "https" and not (site.host == "localhost" or site.host.endswith(".localhost")):
            raise ValueError()
        try:
            ipaddress.ip_address(site.host)
        except ValueError:
            pass
        else:
            raise ValueError()
        value = site.host if requested is None else text(requested, 253)
        rp = idna.encode(value, uts46=True, std3_rules=True).decode("ascii").lower()
        if rp != value or rp.endswith(".") or suffixes()(rp).suffix == rp:
            raise ValueError()
        if rp != site.host and not (base_domain(rp) and site.host.endswith("." + rp)):
            raise ValueError()
        return rp
    except (ValueError, UnicodeError):
        raise PasskeyError("The website cannot use this Passkey domain") from None


def _descriptors(value) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > 100:
        raise PasskeyError("Invalid Passkey credential list")
    ids = []
    for item in value:
        if not isinstance(item, dict) or item.get("type") != "public-key":
            raise PasskeyError("Invalid Passkey credential descriptor")
        decode(item.get("id"))
        ids.append(item["id"])
    return tuple(dict.fromkeys(ids))


@dataclass(frozen=True)
class Request:
    operation: str
    origin: str
    rp_id: str
    challenge: bytes
    credential_ids: tuple[str, ...]
    timeout_ms: int
    rp_name: str = ""
    user_id: str = ""
    user_name: str = ""
    user_display_name: str = ""
    cred_props: bool = False


def parse_request(operation: str, origin: str, options: dict) -> Request:
    try:
        return _parse_request(operation, origin, options)
    except PasskeyError:
        raise
    except (TypeError, ValueError, KeyError, RecursionError, OverflowError):
        raise PasskeyError("Invalid Passkey request") from None


def _parse_request(operation: str, origin: str, options: dict) -> Request:
    if operation not in {"create", "get"} or not isinstance(options, dict):
        raise PasskeyError("Unsupported Passkey request")
    try:
        if len(json.dumps(options, allow_nan=False).encode()) > 65536:
            raise ValueError()
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise PasskeyError("Invalid Passkey request") from None
    challenge = decode(options.get("challenge"))
    timeout = options.get("timeout", 120000)
    if type(timeout) not in {int, float} or not 0 < timeout <= 2**32 - 1:
        raise PasskeyError("Invalid Passkey timeout")
    extensions = options.get("extensions", {})
    # Let the browser's other providers handle extensions we cannot implement.
    if not isinstance(extensions, dict) or set(extensions) - {"credProps"} or type(extensions.get("credProps", False)) is not bool:
        raise PasskeyError("Unsupported Passkey extension")
    common = dict(operation=operation, origin=origin, challenge=challenge, timeout_ms=min(int(timeout), 120000))
    if operation == "create":
        rp, user = options.get("rp"), options.get("user")
        parameters = options.get("pubKeyCredParams")
        if not isinstance(rp, dict) or not isinstance(user, dict) or not isinstance(parameters, list) or len(parameters) > 100:
            raise PasskeyError("Invalid Passkey registration")
        if not any(isinstance(p, dict) and p.get("type") == "public-key" and type(p.get("alg")) is int and p["alg"] == -7 for p in parameters):
            raise PasskeyError("This Passkey provider requires ES256")
        selection = options.get("authenticatorSelection", {})
        if not isinstance(selection, dict) or selection.get("authenticatorAttachment") not in {None, "platform"}:
            raise PasskeyError("Use another provider for a roaming security key")
        if selection.get("residentKey", "preferred") not in {"required", "preferred", "discouraged"} or selection.get("userVerification", "preferred") not in {"required", "preferred", "discouraged"}:
            raise PasskeyError("Unsupported Passkey authenticator selection")
        decode(user.get("id"), maximum=64)
        return Request(**common, rp_id=rp_for(origin, rp.get("id")), rp_name=text(rp.get("name")),
                       user_id=user["id"], user_name=text(user.get("name")), user_display_name=text(user.get("displayName"), empty=True),
                       credential_ids=_descriptors(options.get("excludeCredentials", [])), cred_props=extensions.get("credProps", False))
    if options.get("userVerification", "preferred") not in {"required", "preferred", "discouraged"}:
        raise PasskeyError("Unsupported Passkey user verification")
    return Request(**common, rp_id=rp_for(origin, options.get("rpId")), credential_ids=_descriptors(options.get("allowCredentials", [])))


def _key(credential):
    try:
        key = serialization.load_der_private_key(decode(credential["private_key"], maximum=512), password=None)
        if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1):
            raise ValueError()
        return key
    except (ValueError, TypeError, KeyError):
        raise PasskeyError("Invalid stored Passkey key") from None


def credentials_for(entry) -> list[dict]:
    value = entry.source_metadata.get(NAMESPACE)
    if value is None:
        return []
    if not isinstance(value, dict) or set(value) != {"version", "credentials"} or type(value["version"]) is not int or value["version"] != 1:
        raise PasskeyError("Unsupported Passkey data version")
    items = value["credentials"]
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_CREDENTIALS:
        raise PasskeyError("Invalid stored Passkey list")
    seen = set()
    for item in items:
        if not isinstance(item, dict) or set(item) != FIELDS or type(item["algorithm"]) is not int or item["algorithm"] != -7:
            raise PasskeyError("Invalid stored Passkey")
        decode(item["id"], minimum=32, maximum=32)
        decode(item["user_id"], maximum=64)
        if item["id"] in seen:
            raise PasskeyError("Duplicate stored Passkey identity")
        seen.add(item["id"])
        rp_for("https://" + text(item["rp_id"], 253), item["rp_id"])
        for name in ("rp_name", "user_name", "user_display_name"):
            text(item[name], empty=name == "user_display_name")
        try:
            date = datetime.fromisoformat(item["created_at"])
            if date.tzinfo is None: raise ValueError()
        except (TypeError, ValueError):
            raise PasskeyError("Invalid stored Passkey date") from None
        _key(item)
    return copy.deepcopy(items)


def summaries(entry) -> list[dict]:
    return [{name: item[name] for name in FIELDS - {"private_key"}} for item in credentials_for(entry)]


def redact(value, *, within=False):
    """Public conflict views never disclose private keys, even when revealed."""
    if isinstance(value, list):
        return [redact(item, within=within) for item in value]
    if isinstance(value, dict):
        within = within or {"rp_id", "private_key"}.issubset(value)
        return {name: redact(item, within=within or name == NAMESPACE)
                for name, item in value.items() if not (within and name == "private_key")}
    return value


def combine(left: list, right: list) -> list:
    items = {}
    for item in left + right:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise PasskeyError("Invalid Passkey merge")
        if item["id"] in items and items[item["id"]] != item:
            raise PasskeyError("Passkey identity collision; retain both original accounts")
        items[item["id"]] = copy.deepcopy(item)
    if len(items) > MAX_CREDENTIALS:
        raise PasskeyError("Too many Passkeys in one account")
    return sorted(items.values(), key=lambda item: item["id"])


def set_credentials(entry, items):
    candidate = copy.deepcopy(entry)
    candidate.source_metadata[NAMESPACE] = {"version": 1, "credentials": combine([], items)}
    credentials_for(candidate)
    entry.source_metadata = candidate.source_metadata


def require_payload(local, entries):
    for entry in entries:
        if NAMESPACE in entry.source_metadata:
            if local.payload_version < 3:
                raise PasskeyError("Upgrade the vault before saving Passkeys")
            credentials_for(entry)


def _verified(request, operation, user_verified):
    if not isinstance(request, Request) or request.operation != operation or user_verified is not True:
        raise PasskeyError("Confirm this Passkey request in the desktop app")
    rp_for(request.origin, request.rp_id)


def _auth_data(request, *, attested=b"", backed_up=False):
    flags = AuthenticatorData.FLAG.UP | AuthenticatorData.FLAG.UV | AuthenticatorData.FLAG.BE
    if attested: flags |= AuthenticatorData.FLAG.AT
    if backed_up: flags |= AuthenticatorData.FLAG.BS
    return AuthenticatorData.create(hashlib.sha256(request.rp_id.encode()).digest(), flags, 0, attested)


def register(request: Request, existing: list[dict], *, user_verified: bool) -> tuple[dict, dict]:
    _verified(request, "create", user_verified)
    if any(c["rp_id"] == request.rp_id and c["id"] in request.credential_ids for c in existing):
        raise PasskeyError("This account already has an excluded Passkey")
    key = ec.generate_private_key(ec.SECP256R1())
    credential_id = secrets.token_bytes(32)
    stored = dict(id=encode(credential_id), rp_id=request.rp_id, rp_name=request.rp_name, user_id=request.user_id,
                  user_name=request.user_name, user_display_name=request.user_display_name,
                  created_at=datetime.now(timezone.utc).isoformat(), algorithm=-7,
                  private_key=encode(key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())))
    attested = AttestedCredentialData.create(Aaguid.NONE, credential_id, ES256.from_cryptography_key(key.public_key()))
    auth = _auth_data(request, attested=attested)
    client = CollectedClientData.create("webauthn.create", request.challenge, request.origin)
    response = dict(id=stored["id"], rawId=stored["id"], type="public-key", authenticatorAttachment="platform",
                    clientExtensionResults={"credProps": {"rk": True}} if request.cred_props else {},
                    response=dict(clientDataJSON=encode(client), attestationObject=encode(AttestationObject.create("none", auth, {})),
                                  authenticatorData=encode(auth), publicKeyAlgorithm=-7,
                                  publicKey=encode(key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)),
                                  transports=["internal"]))
    return stored, response


def authenticate(request: Request, credential: dict, *, user_verified: bool, backed_up=False) -> dict:
    _verified(request, "get", user_verified)
    if credential["rp_id"] != request.rp_id or (request.credential_ids and credential["id"] not in request.credential_ids):
        raise PasskeyError("This Passkey does not match the website request")
    auth = _auth_data(request, backed_up=backed_up is True)
    client = CollectedClientData.create("webauthn.get", request.challenge, request.origin)
    signature = _key(credential).sign(bytes(auth) + hashlib.sha256(client).digest(), ec.ECDSA(hashes.SHA256()))
    return dict(id=credential["id"], rawId=credential["id"], type="public-key", authenticatorAttachment="platform", clientExtensionResults={},
                response=dict(clientDataJSON=encode(client), authenticatorData=encode(auth), signature=encode(signature), userHandle=credential["user_id"]))

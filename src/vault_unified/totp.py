"""RFC 6238 codes and local parsing of the standard otpauth URI format."""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import math
import struct
import time
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, unquote, urlsplit


class TotpError(ValueError):
    pass


@dataclass(frozen=True)
class TotpConfig:
    secret: bytes = field(repr=False)
    algorithm: str = "SHA1"
    digits: int = 6
    period: int = 30
    label: str = ""
    issuer: str = ""


def parse_totp(value: str) -> TotpConfig:
    if not isinstance(value, str) or len(value) > 1024:
        raise TotpError("Authenticator key is too long")
    text = value.strip()
    algorithm, digits, period, label, issuer = "SHA1", 6, 30, "", ""
    if text.lower().startswith("otpauth:"):
        try:
            parsed = urlsplit(text)
            if parsed.netloc.lower() != "totp" or parsed.fragment or not parsed.path.lstrip("/"):
                raise ValueError()
            pairs = parse_qsl(parsed.query, keep_blank_values=True, max_num_fields=20)
            params = dict(pairs)
            if len(params) != len(pairs) or "counter" in params:
                raise ValueError()
            text = params["secret"]
            algorithm = params.get("algorithm", "SHA1").upper()
            digits = int(params.get("digits", "6"))
            period = int(params.get("period", "30"))
            label = unquote(parsed.path.lstrip("/"))
            issuer = params.get("issuer", "")
            if len(label) > 256 or len(issuer) > 256:
                raise ValueError()
        except (ValueError, KeyError) as exc:
            raise TotpError("Use a standard otpauth TOTP address with one secret") from exc
    if algorithm not in {"SHA1", "SHA256", "SHA512"} or digits not in {6, 8} or not 1 <= period <= 86400:
        raise TotpError("Unsupported authenticator algorithm, digits or period")
    encoded = "".join(text.split()).upper().rstrip("=")
    try:
        secret = base64.b32decode(encoded + "=" * (-len(encoded) % 8))
        if not 1 <= len(secret) <= 128 or base64.b32encode(secret).decode().rstrip("=") != encoded:
            raise ValueError()
    except (ValueError, binascii.Error) as exc:
        raise TotpError("Enter a valid Base32 authenticator key or otpauth TOTP address") from exc
    return TotpConfig(secret=secret, algorithm=algorithm, digits=digits, period=period, label=label, issuer=issuer)


def current_totp(value: str, *, now: float | None = None) -> dict:
    config = parse_totp(value)
    timestamp = time.time() if now is None else now
    if not math.isfinite(timestamp) or timestamp < 0:
        raise TotpError("System time is invalid")
    counter = int(timestamp // config.period)
    try:
        digest = hmac.new(config.secret, struct.pack(">Q", counter), getattr(hashlib, config.algorithm.lower())).digest()
    except struct.error as exc:
        raise TotpError("System time is outside the supported range") from exc
    offset = digest[-1] & 15
    truncated = int.from_bytes(digest[offset:offset + 4], "big") & 0x7FFFFFFF
    expires = (counter + 1) * config.period
    return {"code": str(truncated % (10 ** config.digits)).zfill(config.digits), "period": config.period,
            "expires_at": expires, "remaining_seconds": expires - timestamp,
            "algorithm": config.algorithm, "digits": config.digits, "label": config.label, "issuer": config.issuer}

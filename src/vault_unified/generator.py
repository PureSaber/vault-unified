from __future__ import annotations

import secrets
import string

LOWER = string.ascii_lowercase
UPPER = string.ascii_uppercase
DIGITS = string.digits
SYMBOLS = "!@#$%^&*()-_=+[]{}|:;,.?"


def generate_password(
    length: int = 20,
    *,
    symbols: bool = True,
    digits: bool = True,
    upper: bool = True,
) -> str:
    if length < 8:
        raise ValueError("Password length must be at least 8")

    alphabet = LOWER
    required: list[str] = [secrets.choice(LOWER)]

    if upper:
        alphabet += UPPER
        required.append(secrets.choice(UPPER))
    if digits:
        alphabet += DIGITS
        required.append(secrets.choice(DIGITS))
    if symbols:
        alphabet += SYMBOLS
        required.append(secrets.choice(SYMBOLS))

    remaining = length - len(required)
    if remaining < 0:
        raise ValueError("Length too short for selected character sets")

    chars = required + [secrets.choice(alphabet) for _ in range(remaining)]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)

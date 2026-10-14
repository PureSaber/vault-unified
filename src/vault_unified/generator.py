from __future__ import annotations

import secrets
import string
from functools import lru_cache
from importlib.resources import files

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
    lower: bool = True,
    allowed: str = "",
    excluded: str = "",
) -> str:
    if not 8 <= length <= 128:
        raise ValueError("Password length must be between 8 and 128")
    if len(allowed) > 128 or len(excluded) > 128 or any(char not in string.printable[:94] for char in allowed + excluded):
        raise ValueError("Character restrictions must use printable ASCII without spaces")
    groups = ([LOWER] if lower else []) + ([UPPER] if upper else []) + ([DIGITS] if digits else []) + ([SYMBOLS] if symbols else [])
    groups = ["".join(char for char in group if (not allowed or char in allowed) and char not in excluded) for group in groups]
    if not groups or any(not group for group in groups):
        raise ValueError("Restrictions remove an enabled character group; change restrictions or disable that group")
    alphabet = "".join(groups)
    if len(alphabet) < 10:
        raise ValueError("Choose at least ten distinct allowed characters")
    chars = [secrets.choice(group) for group in groups]
    chars.extend(secrets.choice(alphabet) for _ in range(length - len(chars)))
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


@lru_cache(maxsize=1)
def passphrase_words() -> tuple[str, ...]:
    data = files("vault_unified").joinpath("wordlists/eff_large_wordlist.txt").read_text(encoding="utf-8")
    words = tuple(line.split()[1] for line in data.splitlines() if line.strip())
    if len(words) != 7776 or len(set(words)) != 7776:
        raise ValueError("Passphrase word list is unavailable")
    return words


def generate_passphrase(words: int = 6, *, separator: str = "-") -> str:
    if not 6 <= words <= 12 or separator not in {"-", " ", ".", "_"}:
        raise ValueError("Choose six to twelve words and a supported separator")
    vocabulary = passphrase_words()
    return separator.join(secrets.choice(vocabulary) for _ in range(words))

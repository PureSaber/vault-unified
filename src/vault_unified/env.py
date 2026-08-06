from __future__ import annotations

import os
from pathlib import Path


def find_project_root() -> Path:
    candidates = [Path.cwd(), *Path(__file__).resolve().parents]
    for base in candidates:
        if (base / "pyproject.toml").exists():
            return base
    return Path.cwd()


def load_env() -> Path:
    """Load .env from project root if present."""
    from dotenv import load_dotenv

    root = find_project_root()
    env_file = root / ".env"
    if env_file.exists():
        load_dotenv(env_file)
    else:
        load_dotenv()
    return root

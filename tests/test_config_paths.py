from __future__ import annotations

from pathlib import Path

from vault_unified.config import get_config_dir


def test_explicit_data_dir_keeps_config_stable_inside_source_checkout(
    tmp_path: Path,
    monkeypatch,
) -> None:
    checkout = tmp_path / "checkout"
    (checkout / "src" / "vault_unified").mkdir(parents=True)
    (checkout / "pyproject.toml").write_text("[project]\nname='synthetic'\n")
    data_dir = tmp_path / "installed-data"

    monkeypatch.chdir(checkout)
    monkeypatch.setenv("VAULT_DATA_DIR", str(data_dir))

    assert get_config_dir() == data_dir / "config"


def test_checkout_without_explicit_data_dir_remains_repo_local(
    tmp_path: Path,
    monkeypatch,
) -> None:
    checkout = tmp_path / "checkout"
    (checkout / "src" / "vault_unified").mkdir(parents=True)
    (checkout / "pyproject.toml").write_text("[project]\nname='synthetic'\n")

    monkeypatch.chdir(checkout)
    monkeypatch.delenv("VAULT_DATA_DIR", raising=False)
    monkeypatch.delenv("VAULT_CONFIG_DIR", raising=False)
    monkeypatch.delenv("VAULT_DIR", raising=False)

    assert get_config_dir() == checkout / ".vault" / "config"

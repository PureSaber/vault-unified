from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERSION = "1.1.0"


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8", newline="\n")


def replace_once(path: str, pattern: str, replacement: str, *, flags: int = 0) -> None:
    text = read(path)
    updated, count = re.subn(pattern, replacement, text, count=1, flags=flags)
    if count != 1:
        raise SystemExit(f"Expected exactly one release-version match in {path}; found {count}")
    write(path, updated)


def update_json(path: str, transform) -> None:
    value = json.loads(read(path))
    transform(value)
    write(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def update_cargo_lock() -> None:
    path = "apps/desktop/src-tauri/Cargo.lock"
    text = read(path)
    pattern = (
        r'(\[\[package\]\]\nname = "vault-unified-desktop"\n)'
        r'version = "[^"]+"'
    )
    updated, count = re.subn(pattern, rf'\g<1>version = "{VERSION}"', text, count=1)
    if count != 1:
        raise SystemExit("Could not update the root Cargo.lock package version")
    write(path, updated)


def release_notes() -> str:
    return f"""# Vault Unified v{VERSION}

Vault Unified v{VERSION} is a security and usability release for the Windows desktop password
vault. It keeps existing encrypted vaults compatible and never migrates a vault automatically.

## Safer secret editing and error handling

- Empty passwords and notes are now preserved as explicit updates.
- Literal mask-like values such as `****` or leading bullet characters are no longer confused
  with desktop placeholders.
- List/search responses expose presence flags instead of fake secret values.
- Failed external CLI commands and timeout messages are sanitized before reaching logs or API
  responses.

## Source-field fidelity

- Bitwarden secondary URIs, match rules, TOTP, custom fields, folders, favorite/reprompt state,
  secure-note type, organization/collection metadata, and attachment presence are retained in
  encrypted source metadata.
- Updates begin from the complete remote item and refuse a write when unsupported ownership or
  attachment state cannot be reconstructed safely.
- Secure Notes are modeled as notes rather than passwords.

## V3-first desktop lifecycle

- The desktop now distinguishes opening, creating, and restoring a vault.
- New desktop vaults require password confirmation and are created directly as Vault Format v3
  using Argon2id and AES-256-GCM envelope encryption.
- Existing legacy vaults remain readable and writable; migration remains explicit and dry-run
  first.
- Restore validates the complete encrypted backup before an atomic, non-overwriting activation.

## Protected integration credentials

- Bitwarden, KeePassXC, and Proton Pass secrets are stored in the operating-system credential
  store instead of desktop-generated plaintext `.env` files.
- Non-secret paths and server names use validated LocalAppData configuration.
- The desktop can save, test, and clear each integration without returning stored secret values.

## Backup and recovery center

- The desktop inventories encrypted automatic and manual backups with hash, size, format,
  verification, and pin state.
- Manual backups can be copied to a separate directory without decrypting them.
- Cleanup is preview-first and can select only verified, unpinned local atomic backups under a
  newest/daily/weekly retention policy.
- Restore retains the displaced active vault, reopens the committed bytes, and invalidates the
  old session.

## Preview-confirmed synchronization

- New installations start local-only with automatic pull and push disabled.
- Desktop synchronization first builds a read-only per-source plan showing additions, updates,
  conflicts, observed deletions, creates, updates, deletes, unavailable sources, and unknown
  outcomes.
- Confirmation tokens are single-use, expire after five minutes, belong to one unlocked
  session, and bind both local and remote state.
- Any local setting change, local entry change, remote change, expiry, session change, or replay
  blocks execution and requires a fresh preview.

## Compatibility and upgrade notes

- Existing v1/v2/v3 vault files are not rewritten merely by installing v{VERSION}.
- New desktop-created vaults use v3; older builds cannot open those v3 files.
- Existing explicit `enabled_sources: null` settings retain their historical “all sources”
  meaning. Missing synchronization settings now use conservative local-only defaults.
- Integration secrets previously stored in `.env` are still accepted as a development fallback,
  but the desktop does not copy them automatically into the OS credential store.
- Keep the v1.0.5 installer and a verified encrypted backup until v{VERSION} has completed the
  post-release smoke checks on the target Windows account.
"""


def main() -> None:
    replace_once(
        "pyproject.toml",
        r'(?m)^version = "[0-9]+\.[0-9]+\.[0-9]+"$',
        f'version = "{VERSION}"',
    )
    replace_once(
        "src/vault_unified/__init__.py",
        r'__version__ = "[^"]+"',
        f'__version__ = "{VERSION}"',
    )
    replace_once(
        "src/vault_unified/api/app.py",
        r'version="[0-9]+\.[0-9]+\.[0-9]+"',
        f'version="{VERSION}"',
    )

    update_json("apps/desktop/package.json", lambda value: value.__setitem__("version", VERSION))

    def package_lock(value: dict) -> None:
        value["version"] = VERSION
        value.setdefault("packages", {}).setdefault("", {})["version"] = VERSION

    update_json("apps/desktop/package-lock.json", package_lock)

    replace_once(
        "apps/desktop/src-tauri/Cargo.toml",
        r'(?m)^version = "[0-9]+\.[0-9]+\.[0-9]+"$',
        f'version = "{VERSION}"',
    )
    update_cargo_lock()
    update_json(
        "apps/desktop/src-tauri/tauri.conf.json",
        lambda value: value.__setitem__("version", VERSION),
    )

    readme = read("README.md")
    readme, count = re.subn(
        r'\*\*v[0-9]+\.[0-9]+\.[0-9]+\*\* — 当前版',
        f'**v{VERSION}** — 当前版',
        readme,
        count=1,
    )
    if count != 1:
        raise SystemExit("README current-version marker was not found")
    marker = "- Bearer Session Token 仅保存在渲染进程内存中；Windows 进程树随桌面应用一同退出\n"
    additions = (
        "- 新建桌面保险库默认使用 Vault Format v3，并要求两次确认主密码\n"
        "- 外部服务秘密使用 Windows Credential Manager，普通配置写入 LocalAppData\n"
        "- 提供可验证、可固定、预览清理和原子恢复的备份中心\n"
        "- 桌面同步采用只读预览 + 一次性确认令牌，默认不启用任何远端源\n"
    )
    if additions not in readme:
        if marker not in readme:
            raise SystemExit("README release feature marker was not found")
        readme = readme.replace(marker, marker + additions, 1)
    write("README.md", readme)

    contract = read("tests/test_release_version_contract.py")
    contract = re.sub(
        r'EXPECTED_VERSION = "[^"]+"',
        f'EXPECTED_VERSION = "{VERSION}"',
        contract,
        count=1,
    )
    contract = re.sub(
        r'docs" / "release-v[0-9]+\.[0-9]+\.[0-9]+\.md"',
        f'docs" / "release-v{VERSION}.md"',
        contract,
        count=1,
    )
    write("tests/test_release_version_contract.py", contract)

    threat_path = "docs/vault-v3-threat-model.md"
    threat = read(threat_path)
    threat = threat.replace(
        "V3 remains\nexplicit opt-in, is included starting with v1.0.5, and has not been made the default.",
        "V3 is included starting with v1.0.5 and becomes the default for newly created\ndesktop vaults in v1.1.0. Legacy CLI/setup creation remains compatibility-oriented, and\nexisting vaults are never migrated automatically.",
    )
    write(threat_path, threat)

    write(f"docs/release-v{VERSION}.md", release_notes())

    cargo_bytes = (ROOT / "apps/desktop/src-tauri/Cargo.lock").read_bytes().replace(
        b"\r\n", b"\n"
    )
    digest = hashlib.sha256(cargo_bytes).hexdigest()
    risk_path = "docs/rustsec-risk-register.md"
    risk = read(risk_path)
    risk, count = re.subn(
        r'canonical LF SHA-256 `[0-9a-f]{64}`',
        f'canonical LF SHA-256 `{digest}`',
        risk,
        count=1,
    )
    if count != 1:
        raise SystemExit("RustSec lockfile digest marker was not found")
    risk = risk.replace(
        "The v1.0.5 release preparation changed only the root package version",
        "The v1.1.0 release preparation changed only the root package version",
    )
    write(risk_path, risk)

    print(f"Prepared all first-party version surfaces for v{VERSION}")
    print(f"Cargo.lock canonical LF SHA-256: {digest}")


if __name__ == "__main__":
    main()

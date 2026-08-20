from __future__ import annotations

import getpass
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from vault_unified.bootstrap import import_token_txt
from vault_unified.clipboard import copy_to_clipboard
from vault_unified.config import get_vault_path
from vault_unified.crypto import (
    inspect_encrypted_file_recovery,
    mask_secret,
    recover_encrypted_file,
)
from vault_unified.env import find_project_root, load_env
from vault_unified.generator import generate_password
from vault_unified.device_keyring import (
    DeviceKeyringError,
    disable_device_unlock,
    disable_rollback_anchor,
    enable_device_unlock,
    enable_rollback_anchor,
    inspect_rollback_anchor,
    verify_and_advance_rollback_anchor,
)
from vault_unified.keyring_store import (
    clear_master_password,
    get_master_password,
    is_remember_enabled,
    save_master_password,
)
from vault_unified.adapters.registry import all_remote_adapters
from vault_unified.manager import UnifiedVault
from vault_unified.migration import (
    MigrationError,
    MigrationOutcome,
    apply_v3_migration,
    discover_migration_receipts,
    inspect_v3_migration,
    recover_migration_receipt,
    plan_v3_migration,
    resume_v3_migration,
    rollback_v3_migration,
)
from vault_unified.models import Source
from vault_unified.storage import (
    RecoveryRequiredError,
    StorageError,
    quarantine_stale_lock,
    require_clean_storage,
)
from vault_unified.v3_crypto import (
    V3CryptoError,
    create_v3_file,
    rotate_v3_dek_file,
    rotate_v3_password_file,
)
from vault_unified.vault_format import (
    V3Container,
    VaultFormatError,
    describe_vault_container,
    inspect_vault_format_file,
    is_framed_vault_file,
)

load_env()
console = Console()


def _read_password(
    prompt: str = "Master password",
    confirm: bool = False,
    *,
    allow_saved: bool = True,
    envvar: str | None = "VAULT_PASSWORD",
) -> str:
    if allow_saved:
        saved = get_master_password()
        if saved:
            return saved

    import os

    if envvar and os.environ.get(envvar):
        return os.environ[envvar]

    pwd = getpass.getpass(f"{prompt}: ")
    if confirm:
        again = getpass.getpass("Confirm master password: ")
        if pwd != again:
            console.print("[red]Passwords do not match.[/red]")
            sys.exit(1)
    return pwd


def _ensure_vault(path: Path, password: str | None) -> UnifiedVault:
    try:
        require_clean_storage(path)
    except RecoveryRequiredError as exc:
        console.print(f"[red]{exc}[/red]")
        console.print("Run: vault storage inspect")
        sys.exit(2)
    if not path.exists():
        console.print("[yellow]Vault not found — creating one now...[/yellow]")
        pwd = password or _read_password("Create master password", confirm=True)
        vault = UnifiedVault.create(path, pwd)
        if click.confirm("Remember master password on this PC (Windows Credential Manager)?", default=True):
            save_master_password(pwd)
            console.print("[green]Master password saved to Windows Credential Manager.[/green]")
        return vault

    is_v3 = isinstance(inspect_vault_format_file(path), V3Container)
    pwd = password or _read_password(allow_saved=not is_framed_vault_file(path))
    try:
        return UnifiedVault(path, pwd)
    except RecoveryRequiredError as exc:
        console.print(f"[red]{exc}[/red]")
        console.print("Run: vault storage inspect")
        sys.exit(2)
    except Exception:
        if not is_v3 and is_remember_enabled():
            clear_master_password()
            console.print("[red]Wrong password (cleared saved password).[/red]")
        else:
            console.print("[red]Wrong password or corrupted vault.[/red]")
        sys.exit(1)


def _open_vault(vault_path: Path, password: str | None) -> UnifiedVault:
    return _ensure_vault(vault_path, password)


def _password_option(name: str = "--password", envvar: str = "VAULT_PASSWORD"):
    return click.option(
        name,
        envvar=envvar,
        help="Master password (auto-loaded from Windows Credential Manager if saved)",
    )


def _print_entries(entries: list) -> None:
    if not entries:
        console.print("[dim]No entries found.[/dim]")
        return
    table = Table(title="Secrets")
    table.add_column("ID", style="dim", max_width=8)
    table.add_column("Title")
    table.add_column("Username")
    table.add_column("Password")
    table.add_column("Source")
    for entry in entries:
        table.add_row(
            entry.id[:8],
            entry.title,
            entry.username,
            mask_secret(entry.password),
            entry.source.value,
        )
    console.print(table)


def _print_sync_results(results: dict[str, dict[str, int]]) -> None:
    for source, stats in results.items():
        conflicts = stats.get("conflicts", 0)
        conflict_txt = f", {conflicts} conflicts" if conflicts else ""
        console.print(
            f"[green]{source}:[/green] "
            f"{stats.get('added', 0)} added, {stats.get('updated', 0)} updated"
            f"{conflict_txt} ({stats.get('total', 0)} total)"
        )


def _print_bidirectional_result(result) -> None:
    for source, stats in result.pulled.items():
        _print_sync_results({source: stats})
    if result.pushed:
        console.print(
            f"[green]push:[/green] {result.pushed.get('pushed', 0)} entries, "
            f"{result.pushed.get('errors', 0)} errors"
        )
    if result.conflicts:
        console.print(f"[yellow]{len(result.conflicts)} conflict(s) — run: vault conflicts list[/yellow]")
    for err in result.errors:
        console.print(f"[red]error:[/red] {err}")


def _interactive_menu(vault_path: Path) -> None:
    vault = _open_vault(vault_path, None)
    console.print(
        Panel.fit(
            "[bold]Vault Unified[/bold] — type a number or command",
            border_style="cyan",
        )
    )
    while True:
        console.print(
            "\n[1] List  [2] Search  [3] Add  [4] Get  [5] Copy  "
            "[6] Edit  [7] Delete  [8] Sync  [9] Status  [0] Exit"
        )
        choice = click.prompt(">", default="1", show_default=False).strip().lower()

        if choice in {"0", "q", "quit", "exit"}:
            break
        if choice in {"1", "list"}:
            _print_entries(vault.list_all())
        elif choice in {"2", "search"}:
            query = click.prompt("Search")
            for entry in vault.search(query):
                console.print(
                    f"[bold]{entry.title}[/bold] user={entry.username or '-'} "
                    f"pass={mask_secret(entry.password)}"
                )
        elif choice in {"3", "add"}:
            title = click.prompt("Title")
            username = click.prompt("Username", default="", show_default=False)
            password = getpass.getpass("Password: ")
            url = click.prompt("URL", default="", show_default=False)
            entry = vault.add(title, username, password, url)
            console.print(f"[green]Added:[/green] {entry.title}")
        elif choice in {"4", "get"}:
            title = click.prompt("Title")
            try:
                entry = vault.resolve(title)
            except (KeyError, ValueError) as exc:
                console.print(f"[red]{exc}[/red]")
                continue
            console.print(f"[bold]{entry.title}[/bold]")
            console.print(f"Username: {entry.username or '-'}")
            if click.confirm("Show full password?", default=False):
                console.print(f"Password: {entry.password}")
            else:
                console.print(f"Password: {mask_secret(entry.password)}")
        elif choice in {"5", "copy"}:
            title = click.prompt("Title")
            try:
                entry = vault.resolve(title)
                copy_to_clipboard(entry.password)
                console.print(f"[green]Password copied for {entry.title}[/green]")
            except (KeyError, ValueError, RuntimeError) as exc:
                console.print(f"[red]{exc}[/red]")
        elif choice in {"6", "edit"}:
            title = click.prompt("Title")
            try:
                entry = vault.resolve(title)
            except (KeyError, ValueError) as exc:
                console.print(f"[red]{exc}[/red]")
                continue
            new_title = click.prompt("Title", default=entry.title)
            new_username = click.prompt("Username", default=entry.username, show_default=True)
            if click.confirm("Change password?", default=False):
                new_password = getpass.getpass("New password: ")
            else:
                new_password = entry.password
            new_url = click.prompt("URL", default=entry.url, show_default=True)
            vault.edit(
                entry.id,
                title=new_title,
                username=new_username,
                password=new_password,
                url=new_url,
            )
            console.print(f"[green]Updated:[/green] {new_title}")
        elif choice in {"7", "delete"}:
            title = click.prompt("Title or ID")
            try:
                entry = vault.resolve(title)
            except (KeyError, ValueError) as exc:
                console.print(f"[red]{exc}[/red]")
                continue
            if click.confirm(f"Delete '{entry.title}'?", default=False):
                vault.delete(entry.id)
                console.print(f"[green]Deleted:[/green] {entry.title}")
        elif choice in {"8", "sync"}:
            results = vault.sync_all()
            if not results:
                console.print("[yellow]No external sources configured.[/yellow]")
            else:
                _print_sync_results(results)
        elif choice in {"9", "status"}:
            for name, state in vault.status().items():
                console.print(f"{name}: {state}")
        else:
            console.print("[dim]Unknown option[/dim]")


@click.group(invoke_without_command=True)
@click.pass_context
@click.version_option(package_name="vault-unified")
def main(ctx: click.Context) -> None:
    """Unified password vault: local encryption + Proton Pass + Bitwarden."""
    if ctx.invoked_subcommand is None:
        _interactive_menu(get_vault_path())


@main.command()
@click.option("--vault-path", type=click.Path(path_type=Path), default=None)
def setup(vault_path: Path | None) -> None:
    """One-time setup wizard: create vault, import token.txt, optional sync."""
    path = vault_path or get_vault_path()
    root = find_project_root()

    console.print(Panel.fit("[bold]Vault Unified — First-time Setup[/bold]", border_style="cyan"))

    if path.exists():
        console.print(f"[yellow]Vault already exists:[/yellow] {path}")
        vault = _open_vault(path, None)
    else:
        password = _read_password("Create master password", confirm=True)
        vault = UnifiedVault.create(path, password)
        console.print(f"[green]Vault created:[/green] {path}")
        if click.confirm("Remember master password on this PC?", default=True):
            save_master_password(password)
            console.print("[green]Saved to Windows Credential Manager.[/green]")

    imported = import_token_txt(root, vault)
    if imported:
        console.print(f"[green]Imported {imported} entry from token.txt[/green]")
    elif (root / "token.txt").exists():
        console.print("[dim]token.txt already imported or empty[/dim]")

    console.print("\nExternal sources:")
    for name, state in vault.status().items():
        if name != "local":
            console.print(f"  {name}: {state}")

    if click.confirm("\nSync from available external sources now?", default=False):
        results = vault.sync_all()
        if results:
            _print_sync_results(results)
        else:
            console.print("[yellow]No external sources available. Edit .env and run: vault sync[/yellow]")

    console.print("\n[bold green]Ready![/bold green] Run [cyan]vault[/cyan] or [cyan]vault.cmd[/cyan] to open the menu.")


@main.command()
@click.option("--vault-path", type=click.Path(path_type=Path), default=None)
def init(vault_path: Path | None) -> None:
    """Create a new encrypted local vault."""
    path = vault_path or get_vault_path()
    if path.exists():
        console.print(f"[yellow]Vault already exists:[/yellow] {path}")
        return
    password = _read_password("Create master password", confirm=True)
    UnifiedVault.create(path, password)
    if click.confirm("Remember master password on this PC?", default=True):
        save_master_password(password)
    console.print(f"[green]Vault created:[/green] {path}")


@main.command("init-v3")
@click.option("--vault-path", type=click.Path(path_type=Path), default=None)
@click.option(
    "--password",
    envvar="VAULT_PASSWORD",
    help="V3 master password; omit to use a hidden prompt",
)
def init_v3(vault_path: Path | None, password: str | None) -> None:
    """Explicitly create a new Vault Format v3 file; never reads or writes keyring state."""
    path = vault_path or get_vault_path()
    pwd = password or _read_password(
        "Create V3 master password",
        confirm=True,
        allow_saved=False,
    )
    try:
        create_v3_file(path, pwd, {"version": 2, "entries": {}})
    except (OSError, StorageError, V3CryptoError, VaultFormatError) as exc:
        raise click.ClickException(str(exc)) from exc
    console.print(f"[green]Vault Format v3 created:[/green] {path}")
    console.print("[dim]Raw V3 passwords are not stored in Windows Credential Manager.[/dim]")


@main.group("v3")
def v3_group() -> None:
    """Explicit Vault Format v3 key operations; never stores a raw v3 password."""


@v3_group.command("rotate-password")
@click.option("--vault-path", type=click.Path(path_type=Path), default=None)
@click.option(
    "--old-password",
    envvar="VAULT_PASSWORD",
    help="Current V3 password; omit to use a hidden prompt",
)
@click.option(
    "--new-password",
    envvar="VAULT_NEW_PASSWORD",
    help="New V3 password; omit to use a hidden confirmation prompt",
)
def v3_rotate_password(
    vault_path: Path | None,
    old_password: str | None,
    new_password: str | None,
) -> None:
    """Atomically rewrap the existing data key under a new password."""
    path = vault_path or get_vault_path()
    old = old_password or _read_password("Current V3 password", allow_saved=False)
    new = new_password or _read_password(
        "New V3 password",
        confirm=True,
        allow_saved=False,
        envvar="VAULT_NEW_PASSWORD",
    )
    try:
        rotate_v3_password_file(path, old, new)
    except (OSError, StorageError, V3CryptoError, VaultFormatError) as exc:
        raise click.ClickException(str(exc)) from exc
    console.print("[green]V3 password slot rotated atomically.[/green]")
    console.print("[yellow]The retained backup remains decryptable with the old password.[/yellow]")


@v3_group.command("rotate-dek")
@click.option("--vault-path", type=click.Path(path_type=Path), default=None)
@click.option(
    "--password",
    envvar="VAULT_PASSWORD",
    help="V3 password; omit to use a hidden prompt",
)
def v3_rotate_dek(vault_path: Path | None, password: str | None) -> None:
    """Atomically replace the data key and re-encrypt the authenticated payload."""
    path = vault_path or get_vault_path()
    pwd = password or _read_password("V3 password", allow_saved=False)
    try:
        rotate_v3_dek_file(path, pwd)
    except (OSError, StorageError, V3CryptoError, VaultFormatError) as exc:
        raise click.ClickException(str(exc)) from exc
    console.print("[green]V3 data key rotated atomically.[/green]")


@v3_group.command("device-enable")
@click.option("--vault-path", type=click.Path(path_type=Path), default=None)
@click.option(
    "--password",
    envvar="VAULT_PASSWORD",
    help="V3 password; omit to use a hidden prompt",
)
def v3_device_enable(vault_path: Path | None, password: str | None) -> None:
    """Store a random device KEK in the approved Windows Credential Manager backend."""

    path = vault_path or get_vault_path()
    pwd = password or _read_password("V3 password", allow_saved=False)
    try:
        credential = enable_device_unlock(path, pwd)
    except (OSError, StorageError, V3CryptoError, VaultFormatError, DeviceKeyringError) as exc:
        raise click.ClickException(str(exc)) from exc
    console.print(f"[green]Device unlock enabled:[/green] slot {credential.slot_id}")
    console.print("[dim]The master password was not written to the keyring.[/dim]")


@v3_group.command("device-disable")
@click.option("--vault-path", type=click.Path(path_type=Path), default=None)
@click.option(
    "--password",
    envvar="VAULT_PASSWORD",
    help="V3 password; omit to use a hidden prompt",
)
def v3_device_disable(vault_path: Path | None, password: str | None) -> None:
    """Remove the device slot atomically, then delete its external keyring record."""

    path = vault_path or get_vault_path()
    pwd = password or _read_password("V3 password", allow_saved=False)
    try:
        disable_device_unlock(path, pwd)
    except (OSError, StorageError, V3CryptoError, VaultFormatError, DeviceKeyringError) as exc:
        raise click.ClickException(str(exc)) from exc
    console.print("[green]Device unlock disabled.[/green]")


@v3_group.group("rollback-anchor")
def v3_rollback_anchor() -> None:
    """Manage the optional non-secret rollback-detection anchor."""


@v3_rollback_anchor.command("enable")
@click.option("--vault-path", type=click.Path(path_type=Path), default=None)
@click.option("--password", envvar="VAULT_PASSWORD")
def v3_anchor_enable(vault_path: Path | None, password: str | None) -> None:
    path = vault_path or get_vault_path()
    pwd = password or _read_password("V3 password", allow_saved=False)
    try:
        anchor = enable_rollback_anchor(path, pwd)
    except (OSError, StorageError, V3CryptoError, VaultFormatError, DeviceKeyringError) as exc:
        raise click.ClickException(str(exc)) from exc
    console.print(
        f"[green]Rollback anchor enabled:[/green] generation {anchor.generation}, "
        f"key generation {anchor.key_generation}"
    )


@v3_rollback_anchor.command("verify")
@click.option("--vault-path", type=click.Path(path_type=Path), default=None)
@click.option("--password", envvar="VAULT_PASSWORD")
def v3_anchor_verify(vault_path: Path | None, password: str | None) -> None:
    path = vault_path or get_vault_path()
    pwd = password or _read_password("V3 password", allow_saved=False)
    try:
        verified = verify_and_advance_rollback_anchor(path, credential=pwd)
    except (OSError, StorageError, V3CryptoError, VaultFormatError, DeviceKeyringError) as exc:
        raise click.ClickException(str(exc)) from exc
    if not verified:
        raise click.ClickException("Rollback anchor is disabled, missing, or unavailable")
    console.print("[green]Rollback anchor verified.[/green]")


@v3_rollback_anchor.command("inspect")
@click.option("--vault-path", type=click.Path(path_type=Path), default=None)
def v3_anchor_inspect(vault_path: Path | None) -> None:
    try:
        metadata = inspect_rollback_anchor(vault_path or get_vault_path())
    except (OSError, StorageError, VaultFormatError, DeviceKeyringError) as exc:
        raise click.ClickException(str(exc)) from exc
    table = Table(title="V3 rollback anchor")
    table.add_column("Field")
    table.add_column("Value")
    for key, value in metadata.items():
        table.add_row(key, str(value).lower() if isinstance(value, bool) else str(value))
    console.print(table)


@v3_rollback_anchor.command("disable")
@click.option("--vault-path", type=click.Path(path_type=Path), default=None)
@click.option("--password", envvar="VAULT_PASSWORD")
def v3_anchor_disable(vault_path: Path | None, password: str | None) -> None:
    path = vault_path or get_vault_path()
    pwd = password or _read_password("V3 password", allow_saved=False)
    try:
        disable_rollback_anchor(path, pwd)
    except (OSError, StorageError, V3CryptoError, VaultFormatError, DeviceKeyringError) as exc:
        raise click.ClickException(str(exc)) from exc
    console.print("[green]Rollback anchor disabled.[/green]")


def _print_migration_outcome(outcome: MigrationOutcome) -> None:
    table = Table(title="Vault Format v3 migration")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("action", outcome.action)
    table.add_row("state", outcome.state)
    table.add_row("changed", str(outcome.changed).lower())
    table.add_row("target", str(outcome.target_path))
    table.add_row("entries", str(outcome.entry_count))
    table.add_row("legacy_sha256", outcome.legacy_sha256)
    table.add_row("candidate_sha256", outcome.candidate_sha256 or "-")
    table.add_row("vault_id", outcome.vault_id or "-")
    table.add_row("required_free_bytes", str(outcome.required_free_bytes))
    table.add_row("available_free_bytes", str(outcome.available_free_bytes))
    table.add_row("receipt", str(outcome.receipt_path) if outcome.receipt_path else "-")
    table.add_row("legacy_backup", str(outcome.backup_path) if outcome.backup_path else "-")
    table.add_row("candidate", str(outcome.candidate_path) if outcome.candidate_path else "-")
    console.print(table)


@main.command("migrate-v3")
@click.option("--apply", "apply_change", is_flag=True, help="Create evidence and activate V3")
@click.option("--vault-path", type=click.Path(path_type=Path), default=None)
@click.option(
    "--legacy-password",
    envvar="VAULT_PASSWORD",
    help="Legacy password; omit to use a hidden prompt",
)
@click.option(
    "--v3-password",
    envvar="VAULT_NEW_PASSWORD",
    help="New V3 password for --apply; omit to use a hidden confirmation prompt",
)
def migrate_v3_cmd(
    apply_change: bool,
    vault_path: Path | None,
    legacy_password: str | None,
    v3_password: str | None,
) -> None:
    """Dry-run legacy-to-V3 migration by default; --apply is explicit and recoverable."""
    path = vault_path or get_vault_path()
    legacy = legacy_password or _read_password(
        "Legacy vault password",
        allow_saved=False,
        envvar="VAULT_PASSWORD",
    )
    try:
        if apply_change:
            new = v3_password or _read_password(
                "New V3 password",
                confirm=True,
                allow_saved=False,
                envvar="VAULT_NEW_PASSWORD",
            )
            outcome = apply_v3_migration(path, legacy, new)
        else:
            outcome = plan_v3_migration(path, legacy)
    except (MigrationError, StorageError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc
    _print_migration_outcome(outcome)
    if not apply_change:
        console.print("[yellow]Dry-run only; no file or receipt was written.[/yellow]")
    else:
        console.print("[yellow]Retain the immutable legacy backup and receipt.[/yellow]")


@main.group("migration")
def migration_group() -> None:
    """Inspect and explicitly resume interrupted V3 migrations."""


@migration_group.command("list")
@click.option("--vault-path", type=click.Path(path_type=Path), default=None)
def migration_list_cmd(vault_path: Path | None) -> None:
    """List live and journal-referenced migration receipts without writing."""
    path = vault_path or get_vault_path()
    receipts = discover_migration_receipts(path)
    if not receipts:
        console.print("[green]No migration receipts found.[/green]")
        return
    console.print("[bold]Vault Format v3 migration receipts[/bold]")
    for receipt in receipts:
        state = "live" if receipt.exists() else "receipt recovery required"
        console.print(str(receipt), soft_wrap=True)
        console.print(f"  state: {state}")


def _migration_password_options(function):
    function = click.option(
        "--v3-password",
        envvar="VAULT_NEW_PASSWORD",
        help="V3 password; omit to use a hidden prompt",
    )(function)
    function = click.option(
        "--legacy-password",
        envvar="VAULT_PASSWORD",
        help="Legacy password; omit to use a hidden prompt",
    )(function)
    return function


def _migration_passwords(
    legacy_password: str | None,
    v3_password: str | None,
) -> tuple[str, str]:
    legacy = legacy_password or _read_password(
        "Legacy vault password",
        allow_saved=False,
        envvar="VAULT_PASSWORD",
    )
    v3 = v3_password or _read_password(
        "V3 password",
        allow_saved=False,
        envvar="VAULT_NEW_PASSWORD",
    )
    return legacy, v3


@migration_group.command("inspect")
@click.option("--receipt", type=click.Path(path_type=Path, exists=True), required=True)
@_migration_password_options
def migration_inspect_cmd(
    receipt: Path,
    legacy_password: str | None,
    v3_password: str | None,
) -> None:
    """Authenticate all durable evidence and report the next safe action without writing."""
    legacy, v3 = _migration_passwords(legacy_password, v3_password)
    try:
        outcome = inspect_v3_migration(receipt, legacy, v3)
    except (MigrationError, StorageError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc
    _print_migration_outcome(outcome)


@migration_group.command("resume")
@click.option("--apply", "apply_change", is_flag=True, help="Apply the inspected next step")
@click.option("--receipt", type=click.Path(path_type=Path, exists=True), required=True)
@_migration_password_options
def migration_resume_cmd(
    apply_change: bool,
    receipt: Path,
    legacy_password: str | None,
    v3_password: str | None,
) -> None:
    """Dry-run by default; explicitly resume a durable migration receipt with --apply."""
    legacy, v3 = _migration_passwords(legacy_password, v3_password)
    try:
        outcome = resume_v3_migration(receipt, legacy, v3, apply=apply_change)
    except (MigrationError, StorageError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc
    _print_migration_outcome(outcome)
    if not apply_change:
        console.print("[yellow]Dry-run only; use --apply after reviewing this action.[/yellow]")


@migration_group.command("receipt-recover")
@click.option("--transaction-id", default=None)
@click.option("--apply", "apply_change", is_flag=True, help="Apply the receipt recovery plan")
@click.option("--receipt", type=click.Path(path_type=Path), required=True)
def migration_receipt_recover_cmd(
    transaction_id: str | None,
    apply_change: bool,
    receipt: Path,
) -> None:
    """Dry-run by default; recover an interrupted secret-free receipt write."""
    try:
        plan = recover_migration_receipt(
            receipt,
            transaction_id=transaction_id,
            apply=apply_change,
        )
    except (MigrationError, StorageError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc
    mode = "applied" if apply_change else "dry-run"
    console.print(f"[green]{mode}:[/green] {plan.transaction_id} -> {plan.action}")


@main.command("rollback-v3")
@click.option("--apply", "apply_change", is_flag=True, help="Restore the immutable legacy bytes")
@click.option("--receipt", type=click.Path(path_type=Path, exists=True), required=True)
@_migration_password_options
def rollback_v3_cmd(
    apply_change: bool,
    receipt: Path,
    legacy_password: str | None,
    v3_password: str | None,
) -> None:
    """Dry-run by default; restore exact legacy bytes and preserve current V3 with --apply."""
    legacy, v3 = _migration_passwords(legacy_password, v3_password)
    try:
        outcome = rollback_v3_migration(
            receipt,
            legacy,
            v3,
            apply=apply_change,
        )
    except (MigrationError, StorageError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc
    _print_migration_outcome(outcome)
    if not apply_change:
        console.print("[yellow]Dry-run only; use --apply after reviewing this action.[/yellow]")
    else:
        console.print("[yellow]The pre-rollback V3 bytes remain in an atomic backup.[/yellow]")


@main.command("forget")
def forget_password() -> None:
    """Remove saved master password from Windows Credential Manager."""
    clear_master_password()
    console.print("[green]Saved master password removed.[/green]")


@main.group()
def storage() -> None:
    """Inspect and explicitly recover interrupted local writes."""


@storage.command("inspect")
@click.option("--vault-path", type=click.Path(path_type=Path), default=None)
@_password_option()
def storage_inspect(vault_path: Path | None, password: str | None) -> None:
    """Read recovery plans without modifying any file."""
    path = vault_path or get_vault_path()
    pwd = password or _read_password(allow_saved=not is_framed_vault_file(path))
    plans = inspect_encrypted_file_recovery(path, pwd)
    if not plans:
        console.print("[green]No interrupted storage transaction found.[/green]")
        return
    table = Table(title="Storage recovery (read-only)")
    table.add_column("Transaction")
    table.add_column("Action")
    table.add_column("Backup")
    for plan in plans:
        table.add_row(
            plan.transaction_id,
            plan.action,
            plan.backup_path.name if plan.backup_path else "-",
        )
    console.print(table)


@storage.command("recover")
@click.option("--transaction-id", default=None)
@click.option("--apply", "apply_change", is_flag=True, help="Apply the inspected recovery plan")
@click.option("--vault-path", type=click.Path(path_type=Path), default=None)
@_password_option()
def storage_recover(
    transaction_id: str | None,
    apply_change: bool,
    vault_path: Path | None,
    password: str | None,
) -> None:
    """Dry-run by default; --apply performs one deterministic recovery."""
    path = vault_path or get_vault_path()
    pwd = password or _read_password(allow_saved=not is_framed_vault_file(path))
    plan = recover_encrypted_file(
        path,
        pwd,
        transaction_id=transaction_id,
        dry_run=not apply_change,
    )
    mode = "applied" if apply_change else "dry-run"
    console.print(f"[green]{mode}:[/green] {plan.transaction_id} -> {plan.action}")


@storage.command("quarantine-stale-lock")
@click.option("--min-age-seconds", default=600, type=click.IntRange(min=60))
@click.option("--apply", "apply_change", is_flag=True, help="Quarantine the stale lock")
@click.option("--vault-path", type=click.Path(path_type=Path), default=None)
def storage_quarantine_stale_lock(
    min_age_seconds: int,
    apply_change: bool,
    vault_path: Path | None,
) -> None:
    """Dry-run by default; never deletes the stale lock evidence."""
    path = vault_path or get_vault_path()
    result = quarantine_stale_lock(
        path,
        min_age_seconds=min_age_seconds,
        dry_run=not apply_change,
    )
    mode = "quarantined" if apply_change else "would quarantine"
    console.print(f"[green]{mode}:[/green] {result.name}")


@main.group("format")
def format_group() -> None:
    """Inspect vault container metadata without decrypting or writing it."""


@format_group.command("inspect")
@click.option("--vault-path", type=click.Path(path_type=Path), default=None)
def format_inspect(vault_path: Path | None) -> None:
    """Show only non-secret format/version metadata."""
    path = vault_path or get_vault_path()
    metadata = describe_vault_container(inspect_vault_format_file(path))
    table = Table(title="Vault format (read-only)")
    table.add_column("Field")
    table.add_column("Value")
    for key, value in metadata.items():
        table.add_row(key, ", ".join(value) if isinstance(value, list) else str(value))
    console.print(table)


@main.command("status")
@click.option("--vault-path", type=click.Path(path_type=Path), default=None)
@_password_option()
def status_cmd(vault_path: Path | None, password: str | None) -> None:
    """Show vault and integration status."""
    path = vault_path or get_vault_path()
    vault = _open_vault(path, password)
    table = Table(title="Vault Status")
    table.add_column("Component")
    table.add_column("State")
    for name, state in vault.status().items():
        table.add_row(name, state)
    if is_framed_vault_file(path):
        from vault_unified.device_keyring import device_slot_metadata

        remember = "device slot enabled" if device_slot_metadata(path) else "no"
    else:
        remember = "yes" if is_remember_enabled() else "no"
    table.add_row("remember_password", remember)
    console.print(table)


@main.command("list")
@click.option("--source", type=click.Choice([s.value for s in Source]), default=None)
@click.option("--vault-path", type=click.Path(path_type=Path), default=None)
@_password_option()
def list_cmd(source: str | None, vault_path: Path | None, password: str | None) -> None:
    """List stored secrets (passwords masked)."""
    vault = _open_vault(vault_path or get_vault_path(), password)
    src = Source(source) if source else None
    _print_entries(vault.list_all(source=src))


@main.command()
@click.argument("query")
@click.option("--vault-path", type=click.Path(path_type=Path), default=None)
@_password_option()
def search(query: str, vault_path: Path | None, password: str | None) -> None:
    """Search secrets by title, username, url, or notes."""
    vault = _open_vault(vault_path or get_vault_path(), password)
    entries = vault.search(query)
    if not entries:
        console.print("[dim]No matches.[/dim]")
        return
    for entry in entries:
        console.print(
            f"[bold]{entry.title}[/bold] ({entry.source.value}) "
            f"user={entry.username or '-'} pass={mask_secret(entry.password)}"
        )


@main.command()
@click.option("--title", prompt=True)
@click.option("--username", default="")
@click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
@click.option("--url", default="")
@click.option("--notes", default="")
@click.option("--tag", multiple=True)
@click.option("--vault-path", type=click.Path(path_type=Path), default=None)
@_password_option("--vault-password", "VAULT_PASSWORD")
def add(
    title: str,
    username: str,
    password: str,
    url: str,
    notes: str,
    tag: tuple[str, ...],
    vault_path: Path | None,
    vault_password: str | None,
) -> None:
    """Add a secret to the local encrypted vault."""
    vault = _open_vault(vault_path or get_vault_path(), vault_password)
    entry = vault.add(title, username, password, url, notes, list(tag))
    console.print(f"[green]Added:[/green] {entry.title} ({entry.id[:8]})")


@main.command()
@click.argument("identifier")
@click.option("--show-password", is_flag=True, help="Print full password to stdout")
@click.option("--vault-path", type=click.Path(path_type=Path), default=None)
@_password_option()
def get(identifier: str, show_password: bool, vault_path: Path | None, password: str | None) -> None:
    """Get a secret by title or id."""
    vault = _open_vault(vault_path or get_vault_path(), password)
    try:
        entry = vault.resolve(identifier)
    except (KeyError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        sys.exit(1)
    console.print(f"[bold]{entry.title}[/bold]")
    console.print(f"Username: {entry.username or '-'}")
    pwd = entry.password if show_password else mask_secret(entry.password)
    console.print(f"Password: {pwd}")
    if entry.url:
        console.print(f"URL: {entry.url}")
    if entry.notes:
        console.print(f"Notes: {entry.notes}")


@main.command()
@click.argument("identifier")
@click.option(
    "--field",
    type=click.Choice(["password", "username"]),
    default="password",
    help="Which field to copy",
)
@click.option("--vault-path", type=click.Path(path_type=Path), default=None)
@_password_option()
def copy(identifier: str, field: str, vault_path: Path | None, password: str | None) -> None:
    """Copy password or username to clipboard."""
    vault = _open_vault(vault_path or get_vault_path(), password)
    try:
        entry = vault.resolve(identifier)
        value = entry.password if field == "password" else entry.username
        if not value:
            console.print(f"[red]No {field} stored for {entry.title}[/red]")
            sys.exit(1)
        copy_to_clipboard(value)
        console.print(f"[green]Copied {field} for {entry.title}[/green]")
    except (KeyError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        sys.exit(1)
    except RuntimeError as exc:
        console.print(f"[red]Clipboard error:[/red] {exc}")
        sys.exit(1)


@main.command()
@click.argument("identifier")
@click.option("--title")
@click.option("--username")
@click.option("--password", "new_password", hide_input=True)
@click.option("--url")
@click.option("--notes")
@click.option("--vault-path", type=click.Path(path_type=Path), default=None)
@_password_option("--vault-password", "VAULT_PASSWORD")
def edit(
    identifier: str,
    title: str | None,
    username: str | None,
    new_password: str | None,
    url: str | None,
    notes: str | None,
    vault_path: Path | None,
    vault_password: str | None,
) -> None:
    """Edit a secret by title or id. Omit flags for interactive prompts."""
    vault = _open_vault(vault_path or get_vault_path(), vault_password)
    try:
        entry = vault.resolve(identifier)
    except (KeyError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        sys.exit(1)

    if not any([title, username, new_password, url, notes]):
        title = click.prompt("Title", default=entry.title)
        username = click.prompt("Username", default=entry.username, show_default=True)
        if click.confirm("Change password?", default=False):
            new_password = getpass.getpass("New password: ")
        url = click.prompt("URL", default=entry.url, show_default=True)
        notes = click.prompt("Notes", default=entry.notes, show_default=True)

    updated = vault.edit(
        entry.id,
        title=title,
        username=username,
        password=new_password,
        url=url,
        notes=notes,
    )
    console.print(f"[green]Updated:[/green] {updated.title} ({updated.id[:8]})")


@main.command()
@click.option("--length", default=20, show_default=True, type=click.IntRange(8, 128))
@click.option("--no-symbols", is_flag=True, help="Exclude symbols from generated password")
@click.option("--copy", "copy_flag", is_flag=True, help="Copy generated password to clipboard")
def generate(length: int, no_symbols: bool, copy_flag: bool) -> None:
    """Generate a strong random password."""
    pwd = generate_password(length, symbols=not no_symbols)
    console.print(pwd)
    if copy_flag:
        try:
            copy_to_clipboard(pwd)
            console.print("[green]Copied to clipboard.[/green]")
        except RuntimeError as exc:
            console.print(f"[yellow]Could not copy:[/yellow] {exc}")


@main.command()
@click.argument("identifier")
@click.option("--vault-path", type=click.Path(path_type=Path), default=None)
@_password_option()
def delete(identifier: str, vault_path: Path | None, password: str | None) -> None:
    """Delete a secret by title or id."""
    vault = _open_vault(vault_path or get_vault_path(), password)
    try:
        entry = vault.resolve(identifier)
    except (KeyError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        sys.exit(1)
    vault.delete(entry.id)
    console.print(f"[green]Deleted:[/green] {entry.title}")


@main.group()
def import_cmd() -> None:
    """Import secrets from external managers into local vault."""


@import_cmd.command("proton")
@click.option("--vault-path", type=click.Path(path_type=Path), default=None)
@_password_option()
def import_proton(vault_path: Path | None, password: str | None) -> None:
    """Import from Proton Pass (requires pass-cli + PAT)."""
    vault = _open_vault(vault_path or get_vault_path(), password)
    if not vault.proton.is_available():
        console.print(
            "[red]Proton Pass unavailable.[/red] Install pass-cli and set "
            "PROTON_PASS_PERSONAL_ACCESS_TOKEN in .env"
        )
        sys.exit(1)
    count = vault.import_from_proton()
    console.print(
        f"[green]Proton Pass:[/green] {count['added']} added, "
        f"{count['updated']} updated ({count['total']} total)"
    )


@import_cmd.command("bitwarden")
@click.option("--vault-path", type=click.Path(path_type=Path), default=None)
@_password_option()
def import_bitwarden(vault_path: Path | None, password: str | None) -> None:
    """Import from Bitwarden (requires bw CLI + API keys + master password)."""
    vault = _open_vault(vault_path or get_vault_path(), password)
    if not vault.bitwarden.is_available():
        console.print(
            "[red]Bitwarden unavailable.[/red] Install bw and set BW_* vars in .env"
        )
        sys.exit(1)
    count = vault.import_from_bitwarden()
    console.print(
        f"[green]Bitwarden:[/green] {count['added']} added, "
        f"{count['updated']} updated ({count['total']} total)"
    )


@import_cmd.command("keepassxc")
@click.option("--vault-path", type=click.Path(path_type=Path), default=None)
@_password_option()
def import_keepassxc(vault_path: Path | None, password: str | None) -> None:
    """Import from KeePassXC (requires keepassxc-cli + .kdbx path in .env)."""
    vault = _open_vault(vault_path or get_vault_path(), password)
    if not vault.keepassxc.is_available():
        console.print(
            "[red]KeePassXC unavailable.[/red] Install KeePassXC and set "
            "KEEPASSXC_DATABASE / KEEPASSXC_PASSWORD in .env"
        )
        sys.exit(1)
    count = vault.import_from_keepassxc()
    console.print(
        f"[green]KeePassXC:[/green] {count['added']} added, "
        f"{count['updated']} updated ({count['total']} total)"
    )


@import_cmd.command("gopass")
@click.option("--vault-path", type=click.Path(path_type=Path), default=None)
@_password_option()
def import_gopass(vault_path: Path | None, password: str | None) -> None:
    """Import from gopass (requires gopass CLI + initialized store)."""
    vault = _open_vault(vault_path or get_vault_path(), password)
    if not vault.gopass.is_available():
        console.print(
            "[red]gopass unavailable.[/red] Run scripts/setup-gopass.ps1 or "
            "initialize gopass and set GOPASS_* in .env"
        )
        sys.exit(1)
    count = vault.import_from_gopass()
    console.print(
        f"[green]gopass:[/green] {count['added']} added, "
        f"{count['updated']} updated ({count['total']} total)"
    )


@main.command()
@click.option("--bidirectional", "-b", is_flag=True, help="Pull and push with conflict detection")
@click.option("--vault-path", type=click.Path(path_type=Path), default=None)
@_password_option()
def sync(vault_path: Path | None, password: str | None, bidirectional: bool) -> None:
    """Sync with external sources (pull only, or bidirectional with -b)."""
    vault = _open_vault(vault_path or get_vault_path(), password)
    if bidirectional:
        result = vault.sync_bidirectional()
        _print_bidirectional_result(result)
        return
    results = vault.sync_all()
    if not results:
        console.print("[yellow]No external sources available.[/yellow]")
        return
    _print_sync_results(results)


@main.command()
@click.argument("identifier", required=False)
@click.option("--all", "push_all", is_flag=True, help="Push all dirty entries")
@click.option("--vault-path", type=click.Path(path_type=Path), default=None)
@_password_option()
def push(
    identifier: str | None,
    push_all: bool,
    vault_path: Path | None,
    password: str | None,
) -> None:
    """Push local changes to all enabled external sources."""
    vault = _open_vault(vault_path or get_vault_path(), password)
    if push_all:
        result = vault.push_all_dirty()
        console.print(f"[green]Pushed {result['pushed']} entries ({result['errors']} errors)[/green]")
        return
    if not identifier:
        console.print("[red]Provide entry title/id or use --all[/red]")
        sys.exit(1)
    entry = vault.resolve(identifier)
    result = vault.push_entry(entry.id)
    console.print(f"[green]Pushed to {result['pushed']} target(s)[/green]")


@main.group()
def conflicts() -> None:
    """Manage sync conflicts."""


@conflicts.command("list")
@click.option("--vault-path", type=click.Path(path_type=Path), default=None)
@_password_option()
def conflicts_list(vault_path: Path | None, password: str | None) -> None:
    """List unresolved sync conflicts."""
    vault = _open_vault(vault_path or get_vault_path(), password)
    items = vault.list_conflicts()
    if not items:
        console.print("[dim]No conflicts.[/dim]")
        return
    for c in items:
        console.print(f"[yellow]{c.id[:8]}[/yellow] {c.title} (default: {c.default_choice})")


@conflicts.command("resolve")
@click.argument("conflict_id")
@click.option(
    "--choice",
    type=click.Choice(["local", "remote", "merge"]),
    required=True,
)
@click.option("--vault-path", type=click.Path(path_type=Path), default=None)
@_password_option()
def conflicts_resolve(
    conflict_id: str,
    choice: str,
    vault_path: Path | None,
    password: str | None,
) -> None:
    """Resolve a sync conflict."""
    vault = _open_vault(vault_path or get_vault_path(), password)
    try:
        entry = vault.resolve_conflict(conflict_id, choice)
    except KeyError as exc:
        console.print(f"[red]Not found:[/red] {exc}")
        sys.exit(1)
    console.print(f"[green]Resolved:[/green] {entry.title}")


@main.group()
def sources() -> None:
    """Manage which external sources participate in sync."""


@sources.command("list")
@click.option("--vault-path", type=click.Path(path_type=Path), default=None)
@_password_option()
def sources_list(vault_path: Path | None, password: str | None) -> None:
    """List external sources with configured and enabled state."""
    vault = _open_vault(vault_path or get_vault_path(), password)
    prefs = vault.get_prefs()
    enabled = {s.value for s in prefs.get_enabled_sources()}
    table = Table(title="External Sources")
    table.add_column("Source")
    table.add_column("Status")
    table.add_column("Sync")
    for adapter in all_remote_adapters():
        tag = "enabled" if adapter.source.value in enabled else "disabled"
        table.add_row(adapter.source.value, adapter.status_message(), tag)
    console.print(table)


def _update_enabled_sources(
    vault: UnifiedVault,
    names: tuple[str, ...],
    *,
    enable: bool,
) -> None:
    from vault_unified.models import Source

    prefs = vault.get_prefs()
    current = {s.value for s in prefs.get_enabled_sources()}
    if prefs.enabled_sources is None:
        current = {s.value for s in Source if s != Source.LOCAL}
    for name in names:
        try:
            src = Source(name)
        except ValueError:
            console.print(f"[red]Unknown source:[/red] {name}")
            sys.exit(1)
        if src == Source.LOCAL:
            console.print("[red]Cannot enable/disable local source[/red]")
            sys.exit(1)
        if enable:
            current.add(src.value)
        else:
            current.discard(src.value)
    prefs.enabled_sources = sorted(current)
    vault.save_prefs(prefs.normalize())
    console.print(f"[green]Updated enabled sources:[/green] {', '.join(prefs.enabled_sources) or '(none)'}")


@sources.command("enable")
@click.argument("names", nargs=-1, required=True)
@click.option("--vault-path", type=click.Path(path_type=Path), default=None)
@_password_option()
def sources_enable(
    names: tuple[str, ...],
    vault_path: Path | None,
    password: str | None,
) -> None:
    """Enable one or more external sources for sync."""
    vault = _open_vault(vault_path or get_vault_path(), password)
    _update_enabled_sources(vault, names, enable=True)


@sources.command("disable")
@click.argument("names", nargs=-1, required=True)
@click.option("--vault-path", type=click.Path(path_type=Path), default=None)
@_password_option()
def sources_disable(
    names: tuple[str, ...],
    vault_path: Path | None,
    password: str | None,
) -> None:
    """Disable one or more external sources (stops pull/push, keeps links)."""
    vault = _open_vault(vault_path or get_vault_path(), password)
    _update_enabled_sources(vault, names, enable=False)


@main.command("desktop")
def desktop_cmd() -> None:
    """Start the Tauri desktop app (requires npm install in apps/desktop)."""
    import shutil
    import subprocess
    from vault_unified.env import find_project_root

    root = find_project_root()
    desktop = root / "apps" / "desktop"
    if not (desktop / "package.json").exists():
        console.print("[red]Desktop app not found.[/red]")
        sys.exit(1)
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if not npm:
        console.print("[red]npm not found in PATH.[/red]")
        sys.exit(1)
    console.print("[cyan]Starting Vault Unified desktop...[/cyan]")
    subprocess.Popen([npm, "run", "tauri", "dev"], cwd=str(desktop))


if __name__ == "__main__":
    main()

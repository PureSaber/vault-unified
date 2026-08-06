from __future__ import annotations

import getpass
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from vault_unified.bootstrap import import_token_txt
from vault_unified.config import get_vault_path
from vault_unified.crypto import mask_secret
from vault_unified.env import find_project_root, load_env
from vault_unified.keyring_store import (
    clear_master_password,
    get_master_password,
    is_remember_enabled,
    save_master_password,
)
from vault_unified.manager import UnifiedVault
from vault_unified.models import Source

load_env()
console = Console()


def _read_password(prompt: str = "Master password", confirm: bool = False) -> str:
    saved = get_master_password()
    if saved:
        return saved

    env_key = "VAULT_PASSWORD"
    import os

    if os.environ.get(env_key):
        return os.environ[env_key]

    pwd = getpass.getpass(f"{prompt}: ")
    if confirm:
        again = getpass.getpass("Confirm master password: ")
        if pwd != again:
            console.print("[red]Passwords do not match.[/red]")
            sys.exit(1)
    return pwd


def _ensure_vault(path: Path, password: str | None) -> UnifiedVault:
    if not path.exists():
        console.print("[yellow]Vault not found — creating one now...[/yellow]")
        pwd = password or _read_password("Create master password", confirm=True)
        vault = UnifiedVault.create(path, pwd)
        if click.confirm("Remember master password on this PC (Windows Credential Manager)?", default=True):
            save_master_password(pwd)
            console.print("[green]Master password saved to Windows Credential Manager.[/green]")
        return vault

    pwd = password or _read_password()
    try:
        return UnifiedVault(path, pwd)
    except Exception:
        if is_remember_enabled():
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
            "\n[1] List  [2] Search  [3] Add  [4] Get  [5] Sync  [6] Status  [0] Exit"
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
            entry = vault.get_by_title(title)
            if not entry:
                console.print(f"[red]Not found:[/red] {title}")
                continue
            console.print(f"[bold]{entry.title}[/bold]")
            console.print(f"Username: {entry.username or '-'}")
            if click.confirm("Show full password?", default=False):
                console.print(f"Password: {entry.password}")
            else:
                console.print(f"Password: {mask_secret(entry.password)}")
        elif choice in {"5", "sync"}:
            results = vault.sync_all()
            if not results:
                console.print("[yellow]No external sources configured.[/yellow]")
            else:
                for source, count in results.items():
                    console.print(f"[green]{source}:[/green] {count} imported")
        elif choice in {"6", "status"}:
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
            for source, count in results.items():
                console.print(f"[green]{source}:[/green] {count} imported")
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


@main.command("forget")
def forget_password() -> None:
    """Remove saved master password from Windows Credential Manager."""
    clear_master_password()
    console.print("[green]Saved master password removed.[/green]")


@main.command("status")
@click.option("--vault-path", type=click.Path(path_type=Path), default=None)
@_password_option()
def status_cmd(vault_path: Path | None, password: str | None) -> None:
    """Show vault and integration status."""
    vault = _open_vault(vault_path or get_vault_path(), password)
    table = Table(title="Vault Status")
    table.add_column("Component")
    table.add_column("State")
    for name, state in vault.status().items():
        table.add_row(name, state)
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
@click.argument("title")
@click.option("--show-password", is_flag=True, help="Print full password to stdout")
@click.option("--vault-path", type=click.Path(path_type=Path), default=None)
@_password_option()
def get(title: str, show_password: bool, vault_path: Path | None, password: str | None) -> None:
    """Get a secret by title."""
    vault = _open_vault(vault_path or get_vault_path(), password)
    entry = vault.get_by_title(title)
    if not entry:
        console.print(f"[red]Not found:[/red] {title}")
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
@click.argument("entry_id")
@click.option("--vault-path", type=click.Path(path_type=Path), default=None)
@_password_option()
def delete(entry_id: str, vault_path: Path | None, password: str | None) -> None:
    """Delete a secret by id prefix or full id."""
    vault = _open_vault(vault_path or get_vault_path(), password)
    target = None
    for entry in vault.list_all():
        if entry.id == entry_id or entry.id.startswith(entry_id):
            target = entry
            break
    if not target:
        console.print(f"[red]Not found:[/red] {entry_id}")
        sys.exit(1)
    vault.delete(target.id)
    console.print(f"[green]Deleted:[/green] {target.title}")


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
    console.print(f"[green]Imported {count} entries from Proton Pass.[/green]")


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
    console.print(f"[green]Imported {count} entries from Bitwarden.[/green]")


@main.command()
@click.option("--vault-path", type=click.Path(path_type=Path), default=None)
@_password_option()
def sync(vault_path: Path | None, password: str | None) -> None:
    """Import from all available external sources."""
    vault = _open_vault(vault_path or get_vault_path(), password)
    results = vault.sync_all()
    if not results:
        console.print("[yellow]No external sources available.[/yellow]")
        return
    for source, count in results.items():
        console.print(f"[green]{source}:[/green] {count} entries imported")


if __name__ == "__main__":
    main()

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
from vault_unified.crypto import mask_secret
from vault_unified.env import find_project_root, load_env
from vault_unified.generator import generate_password
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
    """Push local changes to Proton Pass and Bitwarden."""
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


@main.command("desktop")
def desktop_cmd() -> None:
    """Start the Tauri desktop app (requires npm install in apps/desktop)."""
    import subprocess
    from vault_unified.env import find_project_root

    root = find_project_root()
    desktop = root / "apps" / "desktop"
    if not (desktop / "package.json").exists():
        console.print("[red]Desktop app not found.[/red]")
        sys.exit(1)
    console.print("[cyan]Starting Vault Unified desktop...[/cyan]")
    subprocess.Popen(
        ["npm", "run", "tauri", "dev"],
        cwd=desktop,
        shell=True,
    )


if __name__ == "__main__":
    main()

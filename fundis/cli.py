from __future__ import annotations

from typing import Optional

import typer

from .agents.base import AgentContext
from .agents.registry import get_agent, list_agent_names
from .auth import (
    clear_auth_config,
    clear_premium_base_rpc_url,
    load_auth_config,
    save_premium_base_rpc_url,
    save_sentichain_api_key,
)
from .config import BASE_CHAIN_ID
from .memory import MemoryService
from .wallets import WalletStore
from .web3_utils import get_web3


app = typer.Typer(help="Fundis agent platform CLI.")
wallet_app = typer.Typer(help="Wallet management.")
agent_app = typer.Typer(help="Agent management.")
auth_app = typer.Typer(help="Authentication and API key management.")

app.add_typer(wallet_app, name="wallet")
app.add_typer(agent_app, name="agent")
app.add_typer(auth_app, name="auth")


# --------------------------------------------------------------------------- #
# Wallet CLI
# --------------------------------------------------------------------------- #
@wallet_app.callback(invoke_without_command=True)
def wallet_main(ctx: typer.Context) -> None:
    """
    Entry point for `fundis wallet`.

    With no subcommand, runs an interactive prompt for:
    - Import private key
    - Export private key
    - Delete wallet
    """
    if ctx.invoked_subcommand is not None:
        return
    _wallet_interactive_menu()


def _wallet_interactive_menu() -> None:
    store = WalletStore()
    while True:
        typer.echo("\n=== Wallet management ===")
        typer.echo("1) List wallets")
        typer.echo("2) Import private key")
        typer.echo("3) Export private key")
        typer.echo("4) Delete wallet")
        typer.echo("q) Quit")
        choice = typer.prompt("Select an option", default="q").strip().lower()

        if choice == "1":
            if not store.wallets:
                typer.echo("No wallets stored yet.")
            else:
                typer.echo("Stored wallets:")
                for idx, w in enumerate(store.wallets):
                    typer.echo(f"[{idx}] {w.name} - {w.address}")
        elif choice == "2":
            pk = typer.prompt("Enter private key (0x...)")
            name = typer.prompt("Optional name", default="").strip() or None
            try:
                wallet = store.add_wallet(pk, name=name)
                typer.echo(f"Imported wallet {wallet.name} at {wallet.address}")
            except Exception as exc:  # noqa: BLE001
                typer.echo(f"Failed to import wallet: {exc!r}")
        elif choice == "3":
            if not store.wallets:
                typer.echo("No wallets to export.")
                continue
            for idx, w in enumerate(store.wallets):
                typer.echo(f"[{idx}] {w.name} - {w.address}")
            idx_str = typer.prompt("Select wallet index")
            try:
                idx = int(idx_str)
                pk = store.export_private_key(idx)
                typer.echo(f"Private key for {store.wallets[idx].address}: {pk}")
            except Exception as exc:  # noqa: BLE001
                typer.echo(f"Invalid selection: {exc!r}")
        elif choice == "4":
            if not store.wallets:
                typer.echo("No wallets to delete.")
                continue
            for idx, w in enumerate(store.wallets):
                typer.echo(f"[{idx}] {w.name} - {w.address}")
            idx_str = typer.prompt("Select wallet index")
            try:
                idx = int(idx_str)
                w = store.get_wallet(idx)
                confirm = typer.confirm(
                    f"Delete wallet {w.name} at {w.address}? This only removes the local record."
                )
                if confirm:
                    store.delete_wallet(idx)
                    typer.echo("Wallet deleted from local store.")
            except Exception as exc:  # noqa: BLE001
                typer.echo(f"Invalid selection: {exc!r}")
        elif choice in {"q", "quit", "exit"}:
            break
        else:
            typer.echo("Unknown option.")


# --------------------------------------------------------------------------- #
# Agent CLI
# --------------------------------------------------------------------------- #
@agent_app.callback(invoke_without_command=True)
def agent_main(ctx: typer.Context) -> None:
    """
    Entry point for `fundis agent`.

    With no subcommand, runs an interactive prompt for:
    - Select agent
    - Select wallet
    - Run update (single step)
    - Unwind (return to USDC)
    """
    if ctx.invoked_subcommand is not None:
        return
    _agent_interactive_menu()


def _select_wallet(store: WalletStore) -> Optional[int]:
    if not store.wallets:
        typer.echo("No wallets configured. Use `fundis wallet` to import one first.")
        return None

    typer.echo("Available wallets:")
    for idx, w in enumerate(store.wallets):
        typer.echo(f"[{idx}] {w.name} - {w.address}")

    idx_str = typer.prompt("Select wallet index (or 'q' to cancel)", default="q").strip()
    if idx_str.lower() in {"q", "quit", "exit"}:
        return None
    try:
        idx = int(idx_str)
        if idx < 0 or idx >= len(store.wallets):
            raise IndexError("out of range")
        return idx
    except Exception:  # noqa: BLE001
        typer.echo("Invalid wallet index.")
        return None


def _select_agent() -> Optional[str]:
    names = list_agent_names()
    if not names:
        typer.echo("No agents registered.")
        return None

    typer.echo("Available agents:")
    for idx, name in enumerate(names):
        typer.echo(f"[{idx}] {name}")

    idx_str = typer.prompt("Select agent index (or 'q' to cancel)", default="q").strip()
    if idx_str.lower() in {"q", "quit", "exit"}:
        return None
    try:
        idx = int(idx_str)
        if idx < 0 or idx >= len(names):
            raise IndexError("out of range")
        return names[idx]
    except Exception:  # noqa: BLE001
        typer.echo("Invalid agent index.")
        return None


def _build_agent_context(wallet_store: WalletStore, wallet_index: int) -> AgentContext:
    wallet = wallet_store.get_wallet(wallet_index)
    w3 = get_web3()
    mem = MemoryService()

    def _printer(msg: str) -> None:
        typer.echo(msg)

    return AgentContext(
        web3=w3,
        wallet_address=wallet.address,
        private_key=wallet.private_key,
        memory=mem,
        print=_printer,
        chain_id=BASE_CHAIN_ID,
    )


def _agent_interactive_menu() -> None:
    wallet_store = WalletStore()
    agent_name = _select_agent()
    if not agent_name:
        return
    wallet_index = _select_wallet(wallet_store)
    if wallet_index is None:
        return

    agent_mod = get_agent(agent_name)
    ctx = _build_agent_context(wallet_store, wallet_index)

    typer.echo(
        f"\nUsing agent '{agent_name}' with wallet {ctx.wallet_address} on chain {ctx.chain_id}."
    )

    while True:
        typer.echo("\n=== Agent management ===")
        typer.echo("1) Update agent (run once)")
        typer.echo("2) Unwind agent (return to USDC)")
        typer.echo("q) Quit")
        choice = typer.prompt("Select an option", default="q").strip().lower()

        if choice == "1":
            agent_mod.run_update(ctx)
        elif choice == "2":
            agent_mod.run_unwind(ctx)
        elif choice in {"q", "quit", "exit"}:
            break
        else:
            typer.echo("Unknown option.")


# --------------------------------------------------------------------------- #
# Auth CLI
# --------------------------------------------------------------------------- #
@auth_app.callback(invoke_without_command=True)
def auth_main(ctx: typer.Context) -> None:
    """
    Entry point for `fundis auth`.

    Manages the SentiChain API key used by all agents.
    """
    if ctx.invoked_subcommand is not None:
        return
    _auth_interactive_menu()


def _auth_interactive_menu() -> None:
    while True:
        typer.echo("\n=== Auth configuration ===")
        typer.echo("1) Show current SentiChain API key (partially masked)")
        typer.echo("2) Set / update SentiChain API key")
        typer.echo("3) Delete SentiChain API key (and other auth data)")
        typer.echo("4) Show current Base RPC endpoint (public or premium)")
        typer.echo("5) Set / update premium Base RPC endpoint")
        typer.echo("6) Delete premium Base RPC endpoint")
        typer.echo("q) Quit")
        choice = typer.prompt("Select an option", default="q").strip().lower()

        cfg = load_auth_config()

        if choice == "1":
            if not cfg or not cfg.sentichain_api_key:
                typer.echo("No SentiChain API key configured.")
            else:
                key = cfg.sentichain_api_key
                if len(key) <= 8:
                    masked = "*" * max(len(key) - 2, 0) + key[-2:]
                else:
                    masked = key[:4] + "*" * (len(key) - 8) + key[-4:]
                typer.echo(f"Current SentiChain API key: {masked}")
        elif choice == "2":
            new_key = typer.prompt(
                "Enter SentiChain API key (input is visible; paste carefully)"
            ).strip()
            if not new_key:
                typer.echo("Empty key, nothing saved.")
                continue
            save_sentichain_api_key(new_key)
            typer.echo("SentiChain API key saved to local auth file (~/.fundis/auth.json).")
        elif choice == "3":
            if not cfg or not cfg.sentichain_api_key:
                typer.echo("No API key configured to delete.")
                continue
            if typer.confirm(
                "Delete the stored SentiChain API key and any premium RPC endpoints?"
            ):
                clear_auth_config()
                typer.echo("SentiChain API key and auth config deleted.")
        elif choice == "4":
            from .config import BASE_RPC_URL

            if cfg and cfg.premium_base_rpc_url:
                typer.echo(f"Premium Base RPC endpoint: {cfg.premium_base_rpc_url}")
            else:
                typer.echo(
                    "No premium Base RPC endpoint configured. "
                    f"Using public endpoint: {BASE_RPC_URL}"
                )
        elif choice == "5":
            new_rpc = typer.prompt(
                "Enter premium Base RPC URL (HTTPS, with your provider key)"
            ).strip()
            if not new_rpc:
                typer.echo("Empty URL, nothing saved.")
                continue
            save_premium_base_rpc_url(new_rpc)
            typer.echo("Premium Base RPC endpoint saved to local auth file (~/.fundis/auth.json).")
        elif choice == "6":
            if not cfg or not cfg.premium_base_rpc_url:
                typer.echo("No premium Base RPC endpoint configured to delete.")
                continue
            if typer.confirm("Delete the stored premium Base RPC endpoint?"):
                clear_premium_base_rpc_url()
                typer.echo("Premium Base RPC endpoint deleted.")
        elif choice in {"q", "quit", "exit"}:
            break
        else:
            typer.echo("Unknown option.")



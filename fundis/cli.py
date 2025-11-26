from __future__ import annotations

from datetime import datetime
from typing import Optional

import typer

from .agents.base import AgentContext, DEFAULT_ALLOCATION_USDC
from .agents.registry import get_agent, list_agent_names
from .auth import (
    clear_auth_config,
    clear_premium_base_rpc_url,
    load_auth_config,
    save_premium_base_rpc_url,
    save_sentichain_api_key,
)
from .config import BASE_CHAIN_ID, BASE_RPC_URL
from .hyperliquid import (
    get_hyperliquid_info,
    get_margin_summary,
    get_all_open_positions,
)
from .memory import MemoryService
from .swidge import (
    deposit_usdc_to_hyperliquid,
    get_arbitrum_web3,
    get_arbitrum_usdc_balance,
    get_arbitrum_eth_balance,
    check_hyperliquid_balance_after_deposit,
    withdraw_usdc_from_hyperliquid,
    get_hyperliquid_withdrawable_balance,
    HYPERLIQUID_WITHDRAWAL_FEE,
    HYPERLIQUID_MIN_WITHDRAWAL,
)
from .wallets import WalletStore
from .web3_utils import get_web3


app = typer.Typer(help="Fundis agent platform CLI.")
wallet_app = typer.Typer(help="Wallet management.")
agent_app = typer.Typer(help="Agent management.")
auth_app = typer.Typer(help="Authentication and API key management.")
swidge_app = typer.Typer(help="Swap and bridge utilities.")
logs_app = typer.Typer(help="View historical agent communications.")

app.add_typer(wallet_app, name="wallet")
app.add_typer(agent_app, name="agent")
app.add_typer(auth_app, name="auth")
app.add_typer(swidge_app, name="swidge")
app.add_typer(logs_app, name="logs")


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

    idx_str = typer.prompt(
        "Select wallet index (or 'q' to cancel)", default="q"
    ).strip()
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


def _build_agent_context(
    wallet_store: WalletStore,
    wallet_index: int,
    allocation_usdc: float | None = None,
) -> AgentContext:
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
        allocation_usdc=(
            allocation_usdc if allocation_usdc is not None else DEFAULT_ALLOCATION_USDC
        ),
    )


def _check_existing_position(wallet_address: str, agent_name: str) -> bool:
    """Check if an allocation/position already exists for this wallet+agent."""
    mem = MemoryService()
    pos = mem.get_position(wallet_address, agent_name)
    return pos is not None


def _prompt_for_allocation(agent_name: str) -> float:
    """Prompt user for allocation amount when creating new position."""
    typer.echo(f"\nNo existing allocation found for {agent_name}.")
    typer.echo(f"Default allocation: {DEFAULT_ALLOCATION_USDC} USDC")
    typer.echo("")

    amount_str = typer.prompt(
        "Enter allocation amount in USDC (or press Enter for default)",
        default=str(DEFAULT_ALLOCATION_USDC),
    ).strip()

    try:
        amount = float(amount_str)
        if amount < 1:
            typer.echo("Minimum allocation is 1 USDC. Using default.")
            return DEFAULT_ALLOCATION_USDC
        return amount
    except ValueError:
        typer.echo("Invalid amount. Using default.")
        return DEFAULT_ALLOCATION_USDC


def _agent_interactive_menu() -> None:
    wallet_store = WalletStore()
    agent_name = _select_agent()
    if not agent_name:
        return
    wallet_index = _select_wallet(wallet_store)
    if wallet_index is None:
        return

    wallet = wallet_store.get_wallet(wallet_index)
    agent_mod = get_agent(agent_name)

    # Check if position exists and determine allocation
    has_position = _check_existing_position(wallet.address, agent_name)
    allocation_usdc = DEFAULT_ALLOCATION_USDC

    # Build initial context (with default allocation for display)
    ctx = _build_agent_context(wallet_store, wallet_index, allocation_usdc)

    typer.echo(
        f"\nUsing agent '{agent_name}' with wallet {ctx.wallet_address} on chain {ctx.chain_id}."
    )

    if has_position:
        mem = MemoryService()
        pos = mem.get_position(wallet.address, agent_name)
        typer.echo(
            f"Existing allocation: {pos.allocated_amount} USDC (position: {pos.current_position})"
        )

    while True:
        typer.echo("\n=== Agent management ===")
        typer.echo("1) Update agent (run once)")
        typer.echo("2) Unwind agent (return to USDC)")
        typer.echo("3) View/change allocation")
        typer.echo("q) Quit")
        choice = typer.prompt("Select an option", default="q").strip().lower()

        if choice == "1":
            # Check if we need to prompt for allocation (no existing position)
            current_has_position = _check_existing_position(wallet.address, agent_name)
            if not current_has_position:
                allocation_usdc = _prompt_for_allocation(agent_name)
                ctx = _build_agent_context(wallet_store, wallet_index, allocation_usdc)
            agent_mod.run_update(ctx)
        elif choice == "2":
            agent_mod.run_unwind(ctx)
        elif choice == "3":
            _view_change_allocation(wallet.address, agent_name)
        elif choice in {"q", "quit", "exit"}:
            break
        else:
            typer.echo("Unknown option.")


def _view_change_allocation(wallet_address: str, agent_name: str) -> None:
    """View and optionally change allocation for an agent."""
    mem = MemoryService()
    pos = mem.get_position(wallet_address, agent_name)

    if not pos:
        typer.echo(
            "\nNo allocation exists yet. Allocation will be set on first update."
        )
        return

    typer.echo(f"\n--- Current Allocation for {agent_name} ---")
    typer.echo(f"Allocated amount: {pos.allocated_amount} USDC")
    typer.echo(f"Current position: {pos.current_position}")
    typer.echo(f"Last updated: {pos.last_updated_at}")

    typer.echo("\nNote: To change allocation, first unwind (return to USDC),")
    typer.echo("then the agent will prompt for a new allocation on next update.")


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
            typer.echo(
                "SentiChain API key saved to local auth file (~/.fundis/auth.json)."
            )
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
            typer.echo(
                "Premium Base RPC endpoint saved to local auth file (~/.fundis/auth.json)."
            )
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


# --------------------------------------------------------------------------- #
# Swidge CLI (Swap + Bridge)
# --------------------------------------------------------------------------- #
@swidge_app.callback(invoke_without_command=True)
def swidge_main(ctx: typer.Context) -> None:
    """
    Entry point for `fundis swidge`.

    Provides swap and bridge utilities:
    - Deposit USDC from Arbitrum to Hyperliquid
    - (More coming soon)
    """
    if ctx.invoked_subcommand is not None:
        return
    _swidge_interactive_menu()


def _swidge_interactive_menu() -> None:
    wallet_store = WalletStore()

    while True:
        typer.echo("\n=== Swidge - Swap & Bridge ===")
        typer.echo("1) Deposit USDC from Arbitrum to Hyperliquid")
        typer.echo("2) Withdraw USDC from Hyperliquid to Arbitrum")
        typer.echo("3) Check Hyperliquid balance")
        typer.echo("4) Check Arbitrum balances")
        typer.echo("q) Quit")
        choice = typer.prompt("Select an option", default="q").strip().lower()

        if choice == "1":
            _deposit_to_hyperliquid(wallet_store)
        elif choice == "2":
            _withdraw_from_hyperliquid(wallet_store)
        elif choice == "3":
            _check_hyperliquid_balance(wallet_store)
        elif choice == "4":
            _check_arbitrum_balances(wallet_store)
        elif choice in {"q", "quit", "exit"}:
            break
        else:
            typer.echo("Unknown option.")


def _deposit_to_hyperliquid(wallet_store: WalletStore) -> None:
    """Interactive flow to deposit USDC from Arbitrum to Hyperliquid."""
    # Select wallet
    wallet_index = _select_wallet(wallet_store)
    if wallet_index is None:
        return

    wallet = wallet_store.get_wallet(wallet_index)
    typer.echo(f"\nUsing wallet: {wallet.address}")

    # Get Arbitrum web3
    try:
        w3 = get_arbitrum_web3()
        typer.echo(f"Connected to Arbitrum (chain ID: {w3.eth.chain_id})")
    except Exception as exc:
        typer.echo(f"Error connecting to Arbitrum: {exc!r}")
        return

    # Show current balances
    typer.echo("\n--- Current Balances on Arbitrum ---")
    try:
        usdc_balance, _ = get_arbitrum_usdc_balance(w3, wallet.address)
        eth_balance = get_arbitrum_eth_balance(w3, wallet.address)
        typer.echo(f"USDC: {usdc_balance:.2f}")
        typer.echo(f"ETH:  {eth_balance:.6f} (for gas)")
    except Exception as exc:
        typer.echo(f"Error fetching balances: {exc!r}")
        return

    if usdc_balance < 5:
        typer.echo(
            "\nMinimum deposit is 5 USDC. Please add more USDC to your Arbitrum wallet."
        )
        return

    if eth_balance < 0.0001:
        typer.echo("\nYou need some ETH on Arbitrum for gas fees.")
        return

    # Get deposit amount
    typer.echo(f"\nMaximum deposit: {usdc_balance:.2f} USDC")
    amount_str = (
        typer.prompt(
            "Enter amount to deposit (or 'max' for full balance)", default="10"
        )
        .strip()
        .lower()
    )

    if amount_str == "max":
        amount = float(usdc_balance)
    else:
        try:
            amount = float(amount_str)
        except ValueError:
            typer.echo("Invalid amount.")
            return

    if amount < 5:
        typer.echo("Minimum deposit is 5 USDC.")
        return

    if amount > float(usdc_balance):
        typer.echo(f"Amount exceeds balance ({usdc_balance:.2f} USDC).")
        return

    # Confirm
    typer.echo(f"\n--- Deposit Summary ---")
    typer.echo(f"From:   {wallet.address} (Arbitrum)")
    typer.echo(f"To:     Hyperliquid")
    typer.echo(f"Amount: {amount:.2f} USDC")
    typer.echo("")

    if not typer.confirm("Proceed with deposit?"):
        typer.echo("Cancelled.")
        return

    # Execute deposit
    typer.echo("")
    result = deposit_usdc_to_hyperliquid(
        w3,
        wallet.address,
        wallet.private_key,
        amount,
        print_fn=typer.echo,
    )

    if result.success:
        typer.echo(
            f"\nSuccessfully deposited {result.amount_deposited:.2f} USDC to Hyperliquid."
        )

        # Optionally check Hyperliquid balance
        if typer.confirm("\nCheck Hyperliquid balance now?"):
            check_hyperliquid_balance_after_deposit(wallet.address, print_fn=typer.echo)
    else:
        typer.echo(f"\nDeposit failed: {result.error}")


def _withdraw_from_hyperliquid(wallet_store: WalletStore) -> None:
    """Interactive flow to withdraw USDC from Hyperliquid to Arbitrum."""
    # Select wallet
    wallet_index = _select_wallet(wallet_store)
    if wallet_index is None:
        return

    wallet = wallet_store.get_wallet(wallet_index)
    typer.echo(f"\nUsing wallet: {wallet.address}")

    # Check Hyperliquid balance
    typer.echo("\n--- Hyperliquid Balance ---")
    try:
        withdrawable = get_hyperliquid_withdrawable_balance(wallet.address)
        typer.echo(f"Withdrawable: {withdrawable:.2f} USDC")
    except Exception as exc:
        typer.echo(f"Error fetching Hyperliquid balance: {exc!r}")
        return

    if withdrawable < HYPERLIQUID_MIN_WITHDRAWAL:
        typer.echo(
            f"\nMinimum withdrawal is {HYPERLIQUID_MIN_WITHDRAWAL} USDC (fee is ${HYPERLIQUID_WITHDRAWAL_FEE})."
        )
        typer.echo(
            f"Your withdrawable balance ({withdrawable:.2f} USDC) is insufficient."
        )
        return

    # Get withdrawal amount
    max_withdraw = withdrawable
    net_max = max_withdraw - HYPERLIQUID_WITHDRAWAL_FEE

    typer.echo(f"\nWithdrawal fee: ${HYPERLIQUID_WITHDRAWAL_FEE:.2f}")
    typer.echo(
        f"Maximum withdrawal: {max_withdraw:.2f} USDC (you'd receive {net_max:.2f} USDC)"
    )

    amount_str = (
        typer.prompt(
            "Enter amount to withdraw (or 'max' for full balance)", default="10"
        )
        .strip()
        .lower()
    )

    if amount_str == "max":
        amount = max_withdraw
    else:
        try:
            amount = float(amount_str)
        except ValueError:
            typer.echo("Invalid amount.")
            return

    if amount < HYPERLIQUID_MIN_WITHDRAWAL:
        typer.echo(f"Minimum withdrawal is {HYPERLIQUID_MIN_WITHDRAWAL} USDC.")
        return

    if amount > withdrawable:
        typer.echo(f"Amount exceeds withdrawable balance ({withdrawable:.2f} USDC).")
        return

    net_amount = amount - HYPERLIQUID_WITHDRAWAL_FEE

    # Ask for destination (default to same address)
    typer.echo(f"\nDefault destination: {wallet.address} (same wallet on Arbitrum)")
    custom_dest = typer.prompt(
        "Enter destination address (or press Enter for default)", default=""
    ).strip()

    destination = custom_dest if custom_dest else wallet.address

    # Confirm
    typer.echo(f"\n--- Withdrawal Summary ---")
    typer.echo(f"From:        Hyperliquid")
    typer.echo(f"To:          {destination} (Arbitrum)")
    typer.echo(f"Amount:      {amount:.2f} USDC")
    typer.echo(f"Fee:         {HYPERLIQUID_WITHDRAWAL_FEE:.2f} USDC")
    typer.echo(f"You receive: {net_amount:.2f} USDC")
    typer.echo("")

    if not typer.confirm("Proceed with withdrawal?"):
        typer.echo("Cancelled.")
        return

    # Execute withdrawal
    typer.echo("")
    result = withdraw_usdc_from_hyperliquid(
        wallet.address,
        wallet.private_key,
        amount,
        destination_address=destination,
        print_fn=typer.echo,
    )

    if result.success:
        typer.echo(f"\nWithdrawal initiated: {result.amount_withdrawn:.2f} USDC")
        typer.echo(
            f"Net amount (after ${result.fee} fee): {result.amount_withdrawn - result.fee:.2f} USDC"
        )
        typer.echo("\nCheck your Arbitrum wallet in 3-5 minutes.")
    else:
        typer.echo(f"\nWithdrawal failed: {result.error}")


def _check_hyperliquid_balance(wallet_store: WalletStore) -> None:
    """Check current balance on Hyperliquid."""
    wallet_index = _select_wallet(wallet_store)
    if wallet_index is None:
        return

    wallet = wallet_store.get_wallet(wallet_index)
    typer.echo(f"\nChecking Hyperliquid balance for: {wallet.address}")

    try:
        info = get_hyperliquid_info()

        margin = get_margin_summary(info, wallet.address)
        positions = get_all_open_positions(info, wallet.address)

        typer.echo("\n--- Hyperliquid Account Summary ---")
        typer.echo(f"Account Value:     ${margin['account_value']:.2f}")
        typer.echo(f"Total Margin Used: ${margin['total_margin_used']:.2f}")
        typer.echo(f"Available Margin:  ${margin['withdrawable']:.2f}")
        typer.echo(f"Margin Ratio:      {margin['margin_ratio']:.1%}")

        if positions:
            typer.echo(f"\n--- Open Positions ({len(positions)}) ---")
            for pos in positions:
                coin = pos.get("coin", "?")
                szi = float(pos.get("szi", 0))
                entry_px = pos.get("entryPx", "?")
                unrealized_pnl = float(pos.get("unrealizedPnl", 0))
                side = "LONG" if szi > 0 else "SHORT"
                typer.echo(
                    f"  {coin}: {side} {abs(szi)} @ ${entry_px} "
                    f"(PnL: ${unrealized_pnl:+.2f})"
                )
        else:
            typer.echo("\nNo open positions.")

    except Exception as exc:
        typer.echo(f"Error fetching Hyperliquid data: {exc!r}")


def _check_arbitrum_balances(wallet_store: WalletStore) -> None:
    """Check current balances on Arbitrum."""
    wallet_index = _select_wallet(wallet_store)
    if wallet_index is None:
        return

    wallet = wallet_store.get_wallet(wallet_index)
    typer.echo(f"\nChecking Arbitrum balances for: {wallet.address}")

    try:
        w3 = get_arbitrum_web3()
        usdc_balance, _ = get_arbitrum_usdc_balance(w3, wallet.address)
        eth_balance = get_arbitrum_eth_balance(w3, wallet.address)

        typer.echo("\n--- Arbitrum Balances ---")
        typer.echo(f"USDC: {usdc_balance:.2f}")
        typer.echo(f"ETH:  {eth_balance:.6f}")

    except Exception as exc:
        typer.echo(f"Error fetching Arbitrum balances: {exc!r}")


# --------------------------------------------------------------------------- #
# Logs CLI
# --------------------------------------------------------------------------- #
@logs_app.callback(invoke_without_command=True)
def logs_main(ctx: typer.Context) -> None:
    """
    Entry point for `fundis logs`.

    View and manage historical agent communications stored in the local database.
    """
    if ctx.invoked_subcommand is not None:
        return
    _logs_interactive_menu()


def _logs_interactive_menu() -> None:
    while True:
        typer.echo("\n=== Agent Logs ===")
        typer.echo("1) View recent logs (all agents)")
        typer.echo("2) View logs by agent")
        typer.echo("3) View logs by wallet")
        typer.echo("4) Search logs")
        typer.echo("5) Log statistics")
        typer.echo("6) Clear logs")
        typer.echo("q) Quit")
        choice = typer.prompt("Select an option", default="q").strip().lower()

        if choice == "1":
            _view_recent_logs()
        elif choice == "2":
            _view_logs_by_agent()
        elif choice == "3":
            _view_logs_by_wallet()
        elif choice == "4":
            _search_logs()
        elif choice == "5":
            _log_statistics()
        elif choice == "6":
            _clear_logs()
        elif choice in {"q", "quit", "exit"}:
            break
        else:
            typer.echo("Unknown option.")


def _format_log_entry(log) -> str:
    """Format a single log entry for display."""
    # Parse and format timestamp
    try:
        dt = datetime.fromisoformat(log.created_at.replace("Z", "+00:00"))
        timestamp = dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        timestamp = log.created_at[:19]  # Fallback to raw string

    level = log.level or "INFO"
    agent = log.agent_name or "system"

    # Truncate message if too long
    message = log.message
    if len(message) > 200:
        message = message[:197] + "..."

    return f"[{timestamp}] [{level}] [{agent}] {message}"


def _display_logs(logs, page: int = 1, total: int = 0, page_size: int = 20) -> None:
    """Display a list of logs with pagination info."""
    if not logs:
        typer.echo("No logs found.")
        return

    typer.echo("")
    for log in logs:
        typer.echo(_format_log_entry(log))

    if total > 0:
        total_pages = (total + page_size - 1) // page_size
        typer.echo(f"\n--- Page {page}/{total_pages} ({total} total logs) ---")


def _view_recent_logs() -> None:
    """View recent logs from all agents."""
    memory = MemoryService()

    page = 1
    page_size = 20

    while True:
        offset = (page - 1) * page_size
        logs = memory.get_logs(limit=page_size, offset=offset)
        total = memory.get_log_count()

        _display_logs(logs, page, total, page_size)

        if total <= page_size:
            break

        total_pages = (total + page_size - 1) // page_size
        typer.echo("\nOptions: [n]ext, [p]rev, [q]uit")
        nav = typer.prompt("Navigate", default="q").strip().lower()

        if nav in {"n", "next"} and page < total_pages:
            page += 1
        elif nav in {"p", "prev", "previous"} and page > 1:
            page -= 1
        elif nav in {"q", "quit", "exit"}:
            break


def _view_logs_by_agent() -> None:
    """View logs filtered by agent."""
    memory = MemoryService()

    agents = memory.get_distinct_agents()
    if not agents:
        typer.echo("No agent logs found.")
        return

    typer.echo("\nAvailable agents:")
    for idx, agent in enumerate(agents):
        count = memory.get_log_count(agent_name=agent)
        typer.echo(f"[{idx}] {agent} ({count} logs)")

    idx_str = typer.prompt("Select agent index (or 'q' to cancel)", default="q").strip()
    if idx_str.lower() in {"q", "quit", "exit"}:
        return

    try:
        idx = int(idx_str)
        if idx < 0 or idx >= len(agents):
            raise IndexError("out of range")
        agent_name = agents[idx]
    except Exception:
        typer.echo("Invalid selection.")
        return

    page = 1
    page_size = 20

    while True:
        offset = (page - 1) * page_size
        logs = memory.get_logs(agent_name=agent_name, limit=page_size, offset=offset)
        total = memory.get_log_count(agent_name=agent_name)

        typer.echo(f"\n--- Logs for {agent_name} ---")
        _display_logs(logs, page, total, page_size)

        if total <= page_size:
            break

        total_pages = (total + page_size - 1) // page_size
        typer.echo("\nOptions: [n]ext, [p]rev, [q]uit")
        nav = typer.prompt("Navigate", default="q").strip().lower()

        if nav in {"n", "next"} and page < total_pages:
            page += 1
        elif nav in {"p", "prev", "previous"} and page > 1:
            page -= 1
        elif nav in {"q", "quit", "exit"}:
            break


def _view_logs_by_wallet() -> None:
    """View logs filtered by wallet."""
    wallet_store = WalletStore()
    wallet_index = _select_wallet(wallet_store)
    if wallet_index is None:
        return

    wallet = wallet_store.get_wallet(wallet_index)
    memory = MemoryService()

    page = 1
    page_size = 20

    while True:
        offset = (page - 1) * page_size
        logs = memory.get_logs(
            wallet_address=wallet.address, limit=page_size, offset=offset
        )
        total = memory.get_log_count(wallet_address=wallet.address)

        typer.echo(
            f"\n--- Logs for wallet {wallet.address[:10]}...{wallet.address[-6:]} ---"
        )
        _display_logs(logs, page, total, page_size)

        if total <= page_size:
            break

        total_pages = (total + page_size - 1) // page_size
        typer.echo("\nOptions: [n]ext, [p]rev, [q]uit")
        nav = typer.prompt("Navigate", default="q").strip().lower()

        if nav in {"n", "next"} and page < total_pages:
            page += 1
        elif nav in {"p", "prev", "previous"} and page > 1:
            page -= 1
        elif nav in {"q", "quit", "exit"}:
            break


def _search_logs() -> None:
    """Search logs by keyword."""
    keyword = typer.prompt("Enter search keyword").strip()
    if not keyword:
        typer.echo("No keyword provided.")
        return

    memory = MemoryService()

    # Get all logs and filter by keyword (simple approach)
    # For large datasets, you'd want to add a LIKE query to MemoryService
    all_logs = memory.get_logs(limit=1000)
    matching = [log for log in all_logs if keyword.lower() in log.message.lower()]

    typer.echo(f"\n--- Search results for '{keyword}' ({len(matching)} matches) ---")

    if not matching:
        typer.echo("No matching logs found.")
        return

    # Show up to 50 results
    for log in matching[:50]:
        typer.echo(_format_log_entry(log))

    if len(matching) > 50:
        typer.echo(f"\n... and {len(matching) - 50} more matches")


def _log_statistics() -> None:
    """Show log statistics."""
    memory = MemoryService()

    total = memory.get_log_count()
    agents = memory.get_distinct_agents()

    typer.echo("\n--- Log Statistics ---")
    typer.echo(f"Total logs: {total}")
    typer.echo(f"Agents with logs: {len(agents)}")

    if agents:
        typer.echo("\nLogs per agent:")
        for agent in agents:
            count = memory.get_log_count(agent_name=agent)
            typer.echo(f"  {agent}: {count}")

    # Count by level
    info_count = memory.get_log_count(level="INFO")
    warn_count = memory.get_log_count(level="WARN")

    typer.echo("\nLogs by level:")
    typer.echo(f"  INFO: {info_count}")
    typer.echo(f"  WARN: {warn_count}")


def _clear_logs() -> None:
    """Clear logs with confirmation."""
    memory = MemoryService()
    total = memory.get_log_count()

    if total == 0:
        typer.echo("No logs to clear.")
        return

    typer.echo(f"\nTotal logs: {total}")
    typer.echo("\nClear options:")
    typer.echo("1) Clear all logs")
    typer.echo("2) Clear logs for specific agent")
    typer.echo("q) Cancel")

    choice = typer.prompt("Select option", default="q").strip().lower()

    if choice == "1":
        if typer.confirm(f"Delete ALL {total} logs? This cannot be undone."):
            deleted = memory.clear_logs()
            typer.echo(f"Deleted {deleted} logs.")
    elif choice == "2":
        agents = memory.get_distinct_agents()
        if not agents:
            typer.echo("No agent logs found.")
            return

        typer.echo("\nAvailable agents:")
        for idx, agent in enumerate(agents):
            count = memory.get_log_count(agent_name=agent)
            typer.echo(f"[{idx}] {agent} ({count} logs)")

        idx_str = typer.prompt("Select agent index").strip()
        try:
            idx = int(idx_str)
            agent_name = agents[idx]
            count = memory.get_log_count(agent_name=agent_name)

            if typer.confirm(f"Delete {count} logs for {agent_name}?"):
                deleted = memory.clear_logs(agent_name=agent_name)
                typer.echo(f"Deleted {deleted} logs.")
        except Exception:
            typer.echo("Invalid selection.")
    elif choice in {"q", "quit", "exit"}:
        typer.echo("Cancelled.")

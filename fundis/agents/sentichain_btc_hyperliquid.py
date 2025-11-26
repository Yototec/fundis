"""
SentiChain BTC Agent on Hyperliquid.

This agent uses SentiChain sentiment data to open/close BTC long positions
on Hyperliquid perpetuals, instead of swapping on a DEX.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import List

import requests

from ..auth import load_auth_config
from ..hyperliquid import (
    check_liquidation_risk,
    get_hyperliquid_exchange,
    get_hyperliquid_info,
    get_position_for_coin,
    get_position_info,
    get_usdc_balance,
    market_close_long_safe,
    market_open_long_safe,
)
from ..memory import MemoryService, Position
from .base import AgentContext


AGENT_NAME = "SentiChain BTC Agent on Hyperliquid"
TICKER = "BTC"
COIN = "BTC"  # Hyperliquid uses "BTC" as the coin symbol

SENTICHAIN_ENDPOINT = (
    "https://api.sentichain.com/agent/get_reasoning_last"
    "?ticker={ticker}&summary_type=l3_event_sentiment_reasoning&api_key={api_key}"
)


@dataclass
class SentimentEvent:
    timestamp: str
    summary: str
    event: str
    sentiment: str


@dataclass
class HyperliquidPosition:
    """Represents a stored position state for Hyperliquid agent."""

    wallet_address: str
    agent_name: str
    ticker: str
    allocated_amount: float  # in USD
    current_position: str  # "FLAT" or "LONG"
    last_updated_at: str


def _parse_reasoning_payload(payload: dict) -> List[SentimentEvent]:
    """
    Parse the SentiChain API response.
    """
    reasoning = (payload.get("reasoning") or "").strip()
    if not reasoning:
        return []

    stripped = reasoning.strip("`")
    start = stripped.find("[")
    end = stripped.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return []

    json_str = stripped[start : end + 1]
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        return []

    events: List[SentimentEvent] = []
    for item in data:
        events.append(
            SentimentEvent(
                timestamp=item.get("timestamp", ""),
                summary=item.get("summary", ""),
                event=item.get("event", ""),
                sentiment=item.get("sentiment", ""),
            )
        )
    return events


def fetch_sentichain_events(
    ticker: str, api_key: str, timeout: float = 10.0
) -> List[SentimentEvent]:
    url = SENTICHAIN_ENDPOINT.format(ticker=ticker, api_key=api_key)
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    payload = resp.json()
    return _parse_reasoning_payload(payload)


def _pretty_print_events(
    ctx: AgentContext, agent_name: str, events: List[SentimentEvent]
) -> None:
    if not events:
        ctx.print("No sentiment events available.")
        return
    ctx.print(f"--- {agent_name} latest sentiment events ({len(events)}) ---")
    for e in events:
        ctx.print(f"{e.timestamp} | [{e.event}] sentiment={e.sentiment} :: {e.summary}")


def _sentiment_counts(events: List[SentimentEvent]) -> Counter:
    c = Counter()
    for e in events:
        sentiment = (e.sentiment or "").lower()
        if sentiment in ("bullish", "bearish"):
            c[sentiment] += 1
    return c


def _log_and_print(
    memory: MemoryService, ctx: AgentContext, agent_name: str, msg: str
) -> None:
    ctx.print(msg)
    memory.log(msg, wallet_address=ctx.wallet_address, agent_name=agent_name)


def _get_stored_position(memory: MemoryService, wallet: str) -> str:
    """
    Get the stored position state from the database.
    Returns 'FLAT' or 'LONG'.
    """
    pos = memory.get_position(wallet, AGENT_NAME)
    if pos:
        return pos.current_position
    return "FLAT"


def _ensure_allocation(
    ctx: AgentContext,
    memory: MemoryService,
) -> bool:
    """
    Ensure we have a position record in the database.
    For Hyperliquid, we just need to track the position state.

    Uses ctx.allocation_usdc for the target amount (default from config).
    The allocation is stored as the user's desired maximum.
    Actual trades will use min(balance, allocation) to prevent failures.
    Returns True if allocation exists or was created, False on error.
    """
    wallet = ctx.wallet_address
    existing = memory.get_position(wallet, AGENT_NAME)
    if existing:
        return True

    allocation_amount = ctx.allocation_usdc
    ctx.print(
        f"No existing allocation found. Setting up {allocation_amount} USDC allocation..."
    )
    ctx.print("Checking USDC balance on Hyperliquid...")

    try:
        info = get_hyperliquid_info()
        usdc_balance = get_usdc_balance(info, wallet)
    except Exception as exc:
        _log_and_print(
            memory,
            ctx,
            AGENT_NAME,
            f"Error checking Hyperliquid balance: {exc!r}. Skipping run.",
        )
        return False

    # Check if wallet has any USDC at all
    if usdc_balance <= 0:
        msg = (
            f"No USDC balance found on Hyperliquid. "
            f"Please deposit USDC via `fundis swidge` before running the agent."
        )
        ctx.print(msg)
        memory.log(msg, wallet_address=wallet, agent_name=AGENT_NAME, level="WARN")
        return False

    # Inform user if their balance is lower than requested allocation
    if usdc_balance < allocation_amount:
        ctx.print(
            f"Note: Current balance ({usdc_balance:.2f} USDC) is less than requested allocation "
            f"({allocation_amount} USDC). Agent will use available balance up to allocation cap."
        )

    # Create position record with user's desired allocation
    pos = Position(
        wallet_address=wallet,
        agent_name=AGENT_NAME,
        ticker=TICKER,
        base_token="USDC",  # Hyperliquid uses USDC as collateral
        quote_token=COIN,
        allocated_amount=float(allocation_amount),
        allocated_amount_raw=int(allocation_amount * 1_000_000),  # USDC has 6 decimals
        current_position="FLAT",
        last_updated_at=datetime.now(timezone.utc).isoformat(),
    )
    memory.upsert_position(pos)
    memory.log(
        f"Allocated {allocation_amount} USDC for agent {AGENT_NAME} on Hyperliquid.",
        wallet_address=wallet,
        agent_name=AGENT_NAME,
    )
    ctx.print(
        f"Allocated {allocation_amount} USDC for this agent on Hyperliquid. "
        f"Trades will use min(balance, {allocation_amount}) USDC."
    )
    return True


def _open_long_position(
    ctx: AgentContext,
    memory: MemoryService,
) -> bool:
    """
    Open a long BTC position on Hyperliquid.

    Uses the safe market order function which:
    1. Checks margin availability before ordering
    2. Uses 2% slippage for market orders on CLOB
    3. Properly parses fill results

    Uses min(available_balance, allocation) to prevent failures.
    """
    wallet = ctx.wallet_address

    # Get allocation from stored position
    pos = memory.get_position(wallet, AGENT_NAME)
    allocation = pos.allocated_amount if pos else ctx.allocation_usdc

    # Get current available balance and use min(balance, allocation)
    try:
        info = get_hyperliquid_info()
        available_balance = get_usdc_balance(info, wallet)
    except Exception as exc:
        _log_and_print(
            memory,
            ctx,
            AGENT_NAME,
            f"Error checking balance: {exc!r}. Skipping.",
        )
        return False

    # Use min of available balance and allocation
    trade_amount = min(available_balance, allocation)

    if trade_amount <= 0:
        _log_and_print(
            memory,
            ctx,
            AGENT_NAME,
            f"No available balance to trade. Balance: {available_balance:.2f} USDC.",
        )
        return False

    if trade_amount < allocation:
        _log_and_print(
            memory,
            ctx,
            AGENT_NAME,
            f"Using available balance {trade_amount:.2f} USDC (allocation: {allocation} USDC).",
        )

    _log_and_print(
        memory,
        ctx,
        AGENT_NAME,
        f"[LIVE] Opening long {COIN} position on Hyperliquid with ~${trade_amount:.2f} notional...",
    )

    try:
        exchange = get_hyperliquid_exchange(ctx.private_key)
        result = market_open_long_safe(
            exchange,
            COIN,
            trade_amount,
            slippage=0.02,  # 2% slippage tolerance for market orders
        )

        if result.success:
            if result.status == "filled":
                _log_and_print(
                    memory,
                    ctx,
                    AGENT_NAME,
                    f"Long position opened. Filled {result.filled_size} {COIN} @ ${result.avg_price:.2f}",
                )
            elif result.status == "resting":
                _log_and_print(
                    memory,
                    ctx,
                    AGENT_NAME,
                    f"Order submitted but resting in book (may need manual review): {result.error}",
                )
            else:
                _log_and_print(
                    memory,
                    ctx,
                    AGENT_NAME,
                    f"Order status: {result.status}",
                )
            return True
        else:
            _log_and_print(
                memory,
                ctx,
                AGENT_NAME,
                f"Order failed [{result.status}]: {result.error}",
            )
            return False

    except Exception as exc:
        _log_and_print(
            memory,
            ctx,
            AGENT_NAME,
            f"Error opening long position: {exc!r}",
        )
        return False


def _close_long_position(
    ctx: AgentContext,
    memory: MemoryService,
) -> bool:
    """
    Close the long BTC position on Hyperliquid.

    Uses the safe market close function with proper error handling.
    """
    wallet = ctx.wallet_address

    # First check if we actually have a position and log details
    try:
        info = get_hyperliquid_info()
        pos_info = get_position_info(info, wallet, COIN)

        if not pos_info:
            _log_and_print(
                memory,
                ctx,
                AGENT_NAME,
                f"No open {COIN} position found on Hyperliquid. Nothing to close.",
            )
            return True

        if pos_info.size <= 0:
            _log_and_print(
                memory,
                ctx,
                AGENT_NAME,
                f"No long position to close (size={pos_info.size}). Position may be short or zero.",
            )
            return True

        _log_and_print(
            memory,
            ctx,
            AGENT_NAME,
            f"[LIVE] Closing long {COIN} position: "
            f"size={pos_info.size}, entry=${pos_info.entry_price:.2f}, "
            f"unrealizedPnl=${pos_info.unrealized_pnl:.2f}, "
            f"liqPrice=${pos_info.liquidation_price if pos_info.liquidation_price else 'N/A'}...",
        )

    except Exception as exc:
        _log_and_print(
            memory,
            ctx,
            AGENT_NAME,
            f"Error checking position: {exc!r}. Attempting close anyway...",
        )

    try:
        exchange = get_hyperliquid_exchange(ctx.private_key)
        result = market_close_long_safe(exchange, COIN, slippage=0.02)

        if result.success:
            if result.status == "filled":
                _log_and_print(
                    memory,
                    ctx,
                    AGENT_NAME,
                    f"Position closed. Sold {result.filled_size} {COIN} @ ${result.avg_price:.2f}",
                )
            elif result.status in ("no_position", "no_long_position"):
                _log_and_print(
                    memory,
                    ctx,
                    AGENT_NAME,
                    f"No position to close: {result.error}",
                )
            else:
                _log_and_print(
                    memory,
                    ctx,
                    AGENT_NAME,
                    f"Close order status: {result.status}",
                )
            return True
        else:
            _log_and_print(
                memory,
                ctx,
                AGENT_NAME,
                f"Close order failed [{result.status}]: {result.error}",
            )
            return False

    except Exception as exc:
        _log_and_print(
            memory,
            ctx,
            AGENT_NAME,
            f"Error closing position: {exc!r}",
        )
        return False


def _check_liquidation_risk(
    ctx: AgentContext,
    memory: MemoryService,
) -> bool:
    """
    Check if current position is at risk of liquidation.
    Returns True if at risk (or error), False if safe.
    """
    try:
        info = get_hyperliquid_info()
        at_risk, message = check_liquidation_risk(info, ctx.wallet_address, COIN)

        if at_risk:
            _log_and_print(
                memory,
                ctx,
                AGENT_NAME,
                f"LIQUIDATION RISK: {message}",
            )
        else:
            ctx.print(f"Position health: {message}")

        return at_risk
    except Exception as exc:
        _log_and_print(
            memory,
            ctx,
            AGENT_NAME,
            f"Error checking liquidation risk: {exc!r}",
        )
        return False  # Don't block on check errors


def _reconcile_position_state(
    ctx: AgentContext,
    memory: MemoryService,
) -> str:
    """
    Reconcile stored position state with actual on-chain position.

    This is important because:
    1. Position may have been liquidated
    2. User may have manually traded
    3. Database may be out of sync

    Returns the reconciled state: 'FLAT' or 'LONG'.
    """
    wallet = ctx.wallet_address
    stored_state = _get_stored_position(memory, wallet)

    try:
        info = get_hyperliquid_info()
        position = get_position_for_coin(info, wallet, COIN)

        if position:
            szi = float(position.get("szi", 0))
            actual_state = "LONG" if szi > 0 else "FLAT"
        else:
            actual_state = "FLAT"

        if stored_state != actual_state:
            _log_and_print(
                memory,
                ctx,
                AGENT_NAME,
                f"Reconciling position: stored={stored_state}, actual={actual_state}. "
                f"Updating to {actual_state}.",
            )
            memory.update_position_side(wallet, AGENT_NAME, actual_state)
            return actual_state

        return stored_state

    except Exception as exc:
        _log_and_print(
            memory,
            ctx,
            AGENT_NAME,
            f"Error reconciling position state: {exc!r}. Using stored state: {stored_state}",
        )
        return stored_state


def run_update(ctx: AgentContext) -> None:
    """
    Main update loop for the Hyperliquid BTC agent.

    Fetches SentiChain sentiment data and opens/closes BTC long positions
    on Hyperliquid perpetuals based on bullish/bearish signals.
    """
    memory = ctx.memory

    # Load API key
    cfg = load_auth_config()
    if not cfg or not cfg.sentichain_api_key.strip():
        _log_and_print(
            memory,
            ctx,
            AGENT_NAME,
            "No SentiChain API key configured. "
            "Run `fundis auth` to set your API key before running agents.",
        )
        return
    api_key = cfg.sentichain_api_key.strip()

    # Fetch sentiment data
    try:
        events = fetch_sentichain_events(TICKER, api_key=api_key)
    except Exception as exc:
        _log_and_print(
            memory,
            ctx,
            AGENT_NAME,
            f"Error fetching SentiChain data for {TICKER}: {exc!r}. Skipping run.",
        )
        return

    _pretty_print_events(ctx, AGENT_NAME, events)
    counts = _sentiment_counts(events)
    bullish = counts.get("bullish", 0)
    bearish = counts.get("bearish", 0)

    _log_and_print(
        memory,
        ctx,
        AGENT_NAME,
        f"Sentiment counts for {TICKER}: bullish={bullish}, bearish={bearish}.",
    )

    if bullish == 0 and bearish == 0:
        _log_and_print(
            memory,
            ctx,
            AGENT_NAME,
            "No bullish or bearish signals found. Skipping update.",
        )
        return

    if bullish == bearish:
        _log_and_print(
            memory,
            ctx,
            AGENT_NAME,
            "Bullish and bearish signals are equal. Skipping update.",
        )
        return

    # Ensure allocation
    if not _ensure_allocation(ctx, memory):
        return

    # Reconcile position state with actual on-chain position
    current_state = _reconcile_position_state(ctx, memory)

    # Check liquidation risk if we have a position
    if current_state == "LONG":
        _check_liquidation_risk(ctx, memory)

    # Decision logic
    if bullish > bearish:
        # Bullish signal - want to be LONG
        if current_state == "FLAT":
            _log_and_print(
                memory,
                ctx,
                AGENT_NAME,
                f"More bullish than bearish. Plan: LONG {TICKER} (open position).",
            )

            if _open_long_position(ctx, memory):
                memory.update_position_side(ctx.wallet_address, AGENT_NAME, "LONG")
        else:
            _log_and_print(
                memory,
                ctx,
                AGENT_NAME,
                f"Already LONG {TICKER}. Holding position.",
            )
    else:
        # Bearish signal - want to be FLAT
        if current_state == "FLAT":
            _log_and_print(
                memory,
                ctx,
                AGENT_NAME,
                f"More bearish than bullish, but already FLAT. No action needed.",
            )
        else:
            _log_and_print(
                memory,
                ctx,
                AGENT_NAME,
                f"More bearish than bullish. Plan: EXIT {TICKER} (close position).",
            )

            if _close_long_position(ctx, memory):
                memory.update_position_side(ctx.wallet_address, AGENT_NAME, "FLAT")


def run_unwind(ctx: AgentContext) -> None:
    """
    Unwind (close) any open position regardless of sentiment.
    """
    memory = ctx.memory

    # Check if we have a stored position
    pos = memory.get_position(ctx.wallet_address, AGENT_NAME)
    if not pos:
        _log_and_print(
            memory,
            ctx,
            AGENT_NAME,
            "No existing position found for this agent and wallet. Nothing to unwind.",
        )
        return

    if pos.current_position == "FLAT":
        _log_and_print(
            memory,
            ctx,
            AGENT_NAME,
            "Position already FLAT. Nothing to unwind.",
        )
        return

    _log_and_print(
        memory,
        ctx,
        AGENT_NAME,
        f"Unwinding position for {TICKER}: {pos.current_position} -> FLAT.",
    )

    if _close_long_position(ctx, memory):
        memory.update_position_side(ctx.wallet_address, AGENT_NAME, "FLAT")

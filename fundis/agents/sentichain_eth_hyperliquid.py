"""
SentiChain ETH Agent on Hyperliquid.

This agent uses SentiChain's product_trading_signal to make trading decisions
and executes long-only positions on Hyperliquid perpetuals.

API Endpoints used:
- product_trading_signal: Trading decisions (LONG/SHORT direction)
- product_research_note: Research notes for logging/display
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

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


AGENT_NAME = "SentiChain ETH Agent on Hyperliquid"
TICKER = "ETH"
COIN = "ETH"

SENTICHAIN_TRADING_SIGNAL_ENDPOINT = (
    "https://api.sentichain.com/agent/get_reasoning_last"
    "?ticker={ticker}&summary_type=product_trading_signal&api_key={api_key}"
)

SENTICHAIN_RESEARCH_NOTE_ENDPOINT = (
    "https://api.sentichain.com/agent/get_reasoning_last"
    "?ticker={ticker}&summary_type=product_research_note&api_key={api_key}"
)


@dataclass
class TradingSignal:
    """Parsed trading signal from SentiChain API."""

    ticker: str
    timestamp: str
    direction: str  # "LONG" or "SHORT"
    confidence: float  # 0.0 to 1.0
    strength: str  # "WEAK", "MODERATE", "STRONG"
    sizing: str  # "QUARTER", "HALF", "FULL"
    max_allocation_pct: int
    leverage_recommended: str
    urgency: str
    suggested_entry: str
    timeframe: str
    stop_loss_condition: str
    take_profit_condition: str
    invalidation: str
    data_quality: str
    conviction_score: int
    risk_rating: str
    raw_json: dict


def _parse_trading_signal(payload: dict) -> Optional[TradingSignal]:
    """
    Parse the trading signal from SentiChain API response.
    
    The API returns:
    {
        "reasoning": "```json\\n{...}\\n```"
    }
    
    The inner JSON contains the trading signal structure.
    """
    reasoning = (payload.get("reasoning") or "").strip()
    if not reasoning:
        return None

    # Strip markdown code block markers
    stripped = reasoning.strip()
    if stripped.startswith("```json"):
        stripped = stripped[7:]
    elif stripped.startswith("```"):
        stripped = stripped[3:]
    if stripped.endswith("```"):
        stripped = stripped[:-3]
    stripped = stripped.strip()

    # Find the JSON object
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None

    json_str = stripped[start : end + 1]
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        return None

    signal = data.get("signal", {})
    position = data.get("position", {})
    timing = data.get("timing", {})
    risk_mgmt = data.get("risk_management", {})
    metadata = data.get("metadata", {})

    return TradingSignal(
        ticker=data.get("ticker", TICKER),
        timestamp=data.get("timestamp", ""),
        direction=signal.get("direction", "").upper(),
        confidence=float(signal.get("confidence", 0)),
        strength=signal.get("strength", ""),
        sizing=position.get("sizing", ""),
        max_allocation_pct=int(position.get("max_allocation_pct", 0)),
        leverage_recommended=position.get("leverage_recommended", "NONE"),
        urgency=timing.get("urgency", ""),
        suggested_entry=timing.get("suggested_entry", ""),
        timeframe=timing.get("timeframe", ""),
        stop_loss_condition=risk_mgmt.get("stop_loss_condition", ""),
        take_profit_condition=risk_mgmt.get("take_profit_condition", ""),
        invalidation=risk_mgmt.get("invalidation", ""),
        data_quality=metadata.get("data_quality", ""),
        conviction_score=int(metadata.get("conviction_score", 0)),
        risk_rating=metadata.get("risk_rating", ""),
        raw_json=data,
    )


def fetch_trading_signal(
    ticker: str, api_key: str, timeout: float = 15.0
) -> Optional[TradingSignal]:
    """Fetch and parse the trading signal from SentiChain API."""
    url = SENTICHAIN_TRADING_SIGNAL_ENDPOINT.format(ticker=ticker, api_key=api_key)
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    payload = resp.json()
    return _parse_trading_signal(payload)


def fetch_research_note(
    ticker: str, api_key: str, timeout: float = 15.0
) -> Optional[str]:
    """Fetch the research note from SentiChain API for logging."""
    url = SENTICHAIN_RESEARCH_NOTE_ENDPOINT.format(ticker=ticker, api_key=api_key)
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    payload = resp.json()
    return (payload.get("reasoning") or "").strip()


def _log_and_print(
    memory: MemoryService, ctx: AgentContext, agent_name: str, msg: str
) -> None:
    """Log a message to both console and memory database."""
    ctx.print(msg)
    memory.log(msg, wallet_address=ctx.wallet_address, agent_name=agent_name)


def _pretty_print_signal(ctx: AgentContext, signal: TradingSignal) -> None:
    """Display the trading signal in a readable format."""
    ctx.print(f"\n--- {AGENT_NAME} Trading Signal ---")
    ctx.print(f"Timestamp: {signal.timestamp}")
    ctx.print(f"Direction: {signal.direction}")
    ctx.print(f"Confidence: {signal.confidence:.0%}")
    ctx.print(f"Strength: {signal.strength}")
    ctx.print(f"Sizing: {signal.sizing}")
    ctx.print(f"Urgency: {signal.urgency}")
    ctx.print(f"Conviction Score: {signal.conviction_score}/10")
    ctx.print(f"Risk Rating: {signal.risk_rating}")
    ctx.print(f"Timeframe: {signal.timeframe}")
    ctx.print(f"Entry: {signal.suggested_entry}")
    ctx.print(f"Stop Loss: {signal.stop_loss_condition}")
    ctx.print(f"Take Profit: {signal.take_profit_condition}")
    ctx.print("---")


def _log_research_note(
    memory: MemoryService, ctx: AgentContext, research_note: str
) -> None:
    """Log the research note for record-keeping."""
    if not research_note:
        return
    
    # Log a summary (first 500 chars) to memory
    summary = research_note[:500] + "..." if len(research_note) > 500 else research_note
    memory.log(
        f"Research Note:\n{summary}",
        wallet_address=ctx.wallet_address,
        agent_name=AGENT_NAME,
    )
    
    # Print a condensed version to console
    lines = research_note.split("\n")
    ctx.print(f"\n--- Research Note Preview ({len(lines)} lines) ---")
    # Show first 10 lines
    for line in lines[:10]:
        ctx.print(line)
    if len(lines) > 10:
        ctx.print(f"... ({len(lines) - 10} more lines, see logs for full note)")
    ctx.print("---")


def _get_stored_position(memory: MemoryService, wallet: str) -> str:
    """Get the stored position state from the database. Returns 'FLAT' or 'LONG'."""
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
    Returns True if allocation exists or was created, False on error.
    """
    wallet = ctx.wallet_address
    existing = memory.get_position(wallet, AGENT_NAME)
    if existing:
        return True

    allocation_amount = ctx.allocation_usdc
    ctx.print(f"No existing allocation found. Setting up {allocation_amount} USDC allocation...")
    ctx.print("Checking USDC balance on Hyperliquid...")

    try:
        info = get_hyperliquid_info()
        usdc_balance = get_usdc_balance(info, wallet)
    except Exception as exc:
        _log_and_print(
            memory, ctx, AGENT_NAME,
            f"Error checking Hyperliquid balance: {exc!r}. Skipping run.",
        )
        return False

    if usdc_balance <= 0:
        msg = (
            f"No USDC balance found on Hyperliquid. "
            f"Please deposit USDC via `fundis swidge` before running the agent."
        )
        ctx.print(msg)
        memory.log(msg, wallet_address=wallet, agent_name=AGENT_NAME, level="WARN")
        return False

    if usdc_balance < allocation_amount:
        ctx.print(
            f"Note: Current balance ({usdc_balance:.2f} USDC) is less than requested allocation "
            f"({allocation_amount} USDC). Agent will use available balance up to allocation cap."
        )

    pos = Position(
        wallet_address=wallet,
        agent_name=AGENT_NAME,
        ticker=TICKER,
        base_token="USDC",
        quote_token=COIN,
        allocated_amount=float(allocation_amount),
        allocated_amount_raw=int(allocation_amount * 1_000_000),
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
    """Open a long ETH position on Hyperliquid."""
    wallet = ctx.wallet_address

    pos = memory.get_position(wallet, AGENT_NAME)
    allocation = pos.allocated_amount if pos else ctx.allocation_usdc

    try:
        info = get_hyperliquid_info()
        available_balance = get_usdc_balance(info, wallet)
    except Exception as exc:
        _log_and_print(memory, ctx, AGENT_NAME, f"Error checking balance: {exc!r}. Skipping.")
        return False

    trade_amount = min(available_balance, allocation)

    if trade_amount <= 0:
        _log_and_print(
            memory, ctx, AGENT_NAME,
            f"No available balance to trade. Balance: {available_balance:.2f} USDC.",
        )
        return False

    if trade_amount < allocation:
        _log_and_print(
            memory, ctx, AGENT_NAME,
            f"Using available balance {trade_amount:.2f} USDC (allocation: {allocation} USDC).",
        )

    _log_and_print(
        memory, ctx, AGENT_NAME,
        f"[LIVE] Opening long {COIN} position on Hyperliquid with ~${trade_amount:.2f} notional...",
    )

    try:
        exchange = get_hyperliquid_exchange(ctx.private_key)
        result = market_open_long_safe(exchange, COIN, trade_amount, slippage=0.02)

        if result.success:
            if result.status == "filled":
                _log_and_print(
                    memory, ctx, AGENT_NAME,
                    f"Long position opened. Filled {result.filled_size} {COIN} @ ${result.avg_price:.2f}",
                )
            elif result.status == "resting":
                _log_and_print(
                    memory, ctx, AGENT_NAME,
                    f"Order submitted but resting in book: {result.error}",
                )
            else:
                _log_and_print(memory, ctx, AGENT_NAME, f"Order status: {result.status}")
            return True
        else:
            _log_and_print(memory, ctx, AGENT_NAME, f"Order failed [{result.status}]: {result.error}")
            return False

    except Exception as exc:
        _log_and_print(memory, ctx, AGENT_NAME, f"Error opening long position: {exc!r}")
        return False


def _close_long_position(
    ctx: AgentContext,
    memory: MemoryService,
) -> bool:
    """Close the long ETH position on Hyperliquid."""
    wallet = ctx.wallet_address

    try:
        info = get_hyperliquid_info()
        pos_info = get_position_info(info, wallet, COIN)

        if not pos_info:
            _log_and_print(
                memory, ctx, AGENT_NAME,
                f"No open {COIN} position found on Hyperliquid. Nothing to close.",
            )
            return True

        if pos_info.size <= 0:
            _log_and_print(
                memory, ctx, AGENT_NAME,
                f"No long position to close (size={pos_info.size}).",
            )
            return True

        _log_and_print(
            memory, ctx, AGENT_NAME,
            f"[LIVE] Closing long {COIN} position: "
            f"size={pos_info.size}, entry=${pos_info.entry_price:.2f}, "
            f"unrealizedPnl=${pos_info.unrealized_pnl:.2f}...",
        )

    except Exception as exc:
        _log_and_print(
            memory, ctx, AGENT_NAME,
            f"Error checking position: {exc!r}. Attempting close anyway...",
        )

    try:
        exchange = get_hyperliquid_exchange(ctx.private_key)
        result = market_close_long_safe(exchange, COIN, slippage=0.02)

        if result.success:
            if result.status == "filled":
                _log_and_print(
                    memory, ctx, AGENT_NAME,
                    f"Position closed. Sold {result.filled_size} {COIN} @ ${result.avg_price:.2f}",
                )
            elif result.status in ("no_position", "no_long_position"):
                _log_and_print(memory, ctx, AGENT_NAME, f"No position to close: {result.error}")
            else:
                _log_and_print(memory, ctx, AGENT_NAME, f"Close order status: {result.status}")
            return True
        else:
            _log_and_print(memory, ctx, AGENT_NAME, f"Close order failed [{result.status}]: {result.error}")
            return False

    except Exception as exc:
        _log_and_print(memory, ctx, AGENT_NAME, f"Error closing position: {exc!r}")
        return False


def _check_liquidation_risk(ctx: AgentContext, memory: MemoryService) -> bool:
    """Check if current position is at risk of liquidation."""
    try:
        info = get_hyperliquid_info()
        at_risk, message = check_liquidation_risk(info, ctx.wallet_address, COIN)

        if at_risk:
            _log_and_print(memory, ctx, AGENT_NAME, f"LIQUIDATION RISK: {message}")
        else:
            ctx.print(f"Position health: {message}")

        return at_risk
    except Exception as exc:
        _log_and_print(memory, ctx, AGENT_NAME, f"Error checking liquidation risk: {exc!r}")
        return False


def _reconcile_position_state(ctx: AgentContext, memory: MemoryService) -> str:
    """
    Reconcile stored position state with actual on-chain position.
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
                memory, ctx, AGENT_NAME,
                f"Reconciling position: stored={stored_state}, actual={actual_state}. Updating to {actual_state}.",
            )
            memory.update_position_side(wallet, AGENT_NAME, actual_state)
            return actual_state

        return stored_state

    except Exception as exc:
        _log_and_print(
            memory, ctx, AGENT_NAME,
            f"Error reconciling position state: {exc!r}. Using stored state: {stored_state}",
        )
        return stored_state


def run_update(ctx: AgentContext) -> None:
    """
    Main update loop for the Hyperliquid ETH agent.

    Fetches SentiChain trading signal and research note, then opens/closes
    ETH long positions on Hyperliquid perpetuals based on the signal direction.
    
    This is a LONG-ONLY agent:
    - LONG signal -> open long position
    - SHORT signal -> close long position (go to flat)
    """
    memory = ctx.memory

    # Load API key
    cfg = load_auth_config()
    if not cfg or not cfg.sentichain_api_key.strip():
        _log_and_print(
            memory, ctx, AGENT_NAME,
            "No SentiChain API key configured. Run `fundis auth` to set your API key.",
        )
        return
    api_key = cfg.sentichain_api_key.strip()

    # Fetch trading signal
    try:
        signal = fetch_trading_signal(TICKER, api_key=api_key)
    except Exception as exc:
        _log_and_print(
            memory, ctx, AGENT_NAME,
            f"Error fetching trading signal for {TICKER}: {exc!r}. Skipping run.",
        )
        return

    if not signal:
        _log_and_print(
            memory, ctx, AGENT_NAME,
            f"No valid trading signal received for {TICKER}. Skipping run.",
        )
        return

    _pretty_print_signal(ctx, signal)

    # Fetch and log research note
    try:
        research_note = fetch_research_note(TICKER, api_key=api_key)
        if research_note:
            _log_research_note(memory, ctx, research_note)
    except Exception as exc:
        ctx.print(f"Note: Could not fetch research note: {exc!r}")

    # Log the trading signal decision
    _log_and_print(
        memory, ctx, AGENT_NAME,
        f"Signal: {signal.direction} | Confidence: {signal.confidence:.0%} | "
        f"Strength: {signal.strength} | Conviction: {signal.conviction_score}/10",
    )

    # Check if signal is valid for action
    if signal.direction not in ("LONG", "SHORT"):
        _log_and_print(
            memory, ctx, AGENT_NAME,
            f"Unknown signal direction: {signal.direction}. Skipping update.",
        )
        return

    # Ensure allocation exists
    if not _ensure_allocation(ctx, memory):
        return

    # Reconcile position state with actual on-chain position
    current_state = _reconcile_position_state(ctx, memory)

    # Check liquidation risk if we have a position
    if current_state == "LONG":
        _check_liquidation_risk(ctx, memory)

    # Decision logic (LONG-ONLY agent)
    if signal.direction == "LONG":
        if current_state == "FLAT":
            _log_and_print(
                memory, ctx, AGENT_NAME,
                f"Signal is LONG. Plan: Open long {TICKER} position.",
            )
            if _open_long_position(ctx, memory):
                memory.update_position_side(ctx.wallet_address, AGENT_NAME, "LONG")
        else:
            _log_and_print(
                memory, ctx, AGENT_NAME,
                f"Signal is LONG, already in LONG position. Holding.",
            )
    else:  # SHORT signal
        if current_state == "FLAT":
            _log_and_print(
                memory, ctx, AGENT_NAME,
                f"Signal is SHORT, but already FLAT. No action needed (long-only agent).",
            )
        else:
            _log_and_print(
                memory, ctx, AGENT_NAME,
                f"Signal is SHORT. Plan: Close long {TICKER} position (go FLAT).",
            )
            if _close_long_position(ctx, memory):
                memory.update_position_side(ctx.wallet_address, AGENT_NAME, "FLAT")


def run_unwind(ctx: AgentContext) -> None:
    """Unwind (close) any open position regardless of signal."""
    memory = ctx.memory

    pos = memory.get_position(ctx.wallet_address, AGENT_NAME)
    if not pos:
        _log_and_print(
            memory, ctx, AGENT_NAME,
            "No existing position found for this agent and wallet. Nothing to unwind.",
        )
        return

    if pos.current_position == "FLAT":
        _log_and_print(memory, ctx, AGENT_NAME, "Position already FLAT. Nothing to unwind.")
        return

    _log_and_print(
        memory, ctx, AGENT_NAME,
        f"Unwinding position for {TICKER}: {pos.current_position} -> FLAT.",
    )

    if _close_long_position(ctx, memory):
        memory.update_position_side(ctx.wallet_address, AGENT_NAME, "FLAT")


from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import List

import requests
from requests import HTTPError
from web3 import Web3
from web3.exceptions import ContractLogicError

from ..config import (
    AERODROME_ROUTER_ADDRESS,
    USDC_ADDRESS,
)
from ..memory import MemoryService, Position
from ..web3_utils import (
    ERC20_MINIMAL_ABI,
    get_erc20_balance,
    get_web3,
    to_checksum,
)
from .base import AgentContext


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


def _parse_reasoning_payload(payload: dict) -> List[SentimentEvent]:
    """
    The API returns a JSON object with a single key "reasoning", whose value
    is a markdown code block containing a JSON array. This helper extracts and
    parses the inner JSON.
    """
    reasoning = (payload.get("reasoning") or "").strip()
    if not reasoning:
        return []

    # Strip surrounding backticks and try to locate the JSON array.
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


def _ensure_allocation(
    ctx: AgentContext,
    agent_name: str,
    ticker: str,
    quote_token: str,
    memory: MemoryService,
) -> Position | None:
    """
    Ensure a 10 USDC allocation exists for (wallet, agent).

    If the wallet holds < 10 USDC on Base, log and return None.
    """
    wallet = ctx.wallet_address
    existing = memory.get_position(wallet, agent_name)
    if existing:
        return existing

    ctx.print("No existing allocation found. Checking USDC balance on Base...")
    w3 = get_web3()
    try:
        human, raw, info = get_erc20_balance(w3, USDC_ADDRESS, wallet)
    except HTTPError as exc:
        msg = (
            f"RPC error while checking USDC balance for allocation: {exc}. "
            "Skipping run; try again in a moment."
        )
        _log_and_print(memory, ctx, agent_name, msg)
        return None
    except Exception as exc:  # noqa: BLE001
        msg = (
            f"Unexpected error while checking USDC balance for allocation: {exc!r}. "
            "Skipping run."
        )
        _log_and_print(memory, ctx, agent_name, msg)
        return None

    needed = Decimal("10")
    if human < needed:
        msg = (
            f"Insufficient USDC balance for allocation: have {human} {info.symbol}, "
            f"need at least {needed} {info.symbol}. Skipping run."
        )
        ctx.print(msg)
        memory.log(msg, wallet_address=wallet, agent_name=agent_name, level="WARN")
        return None

    allocated_amount = float(needed)
    allocated_amount_raw = int(needed * Decimal(10**info.decimals))

    pos = Position(
        wallet_address=wallet,
        agent_name=agent_name,
        ticker=ticker,
        base_token=USDC_ADDRESS,
        quote_token=quote_token,
        allocated_amount=allocated_amount,
        allocated_amount_raw=allocated_amount_raw,
        current_position="USDC",
        last_updated_at=datetime.now(timezone.utc).isoformat(),
    )
    memory.upsert_position(pos)
    memory.log(
        f"Allocated {allocated_amount} USDC for agent {agent_name}.",
        wallet_address=wallet,
        agent_name=agent_name,
    )
    ctx.print(
        f"Allocated {allocated_amount} USDC for this agent. "
        f"Subsequent runs will trade within this allocation."
    )
    return pos


def _log_and_print(
    memory: MemoryService, ctx: AgentContext, agent_name: str, msg: str
) -> None:
    ctx.print(msg)
    memory.log(msg, wallet_address=ctx.wallet_address, agent_name=agent_name)


def _perform_swap(
    ctx: AgentContext,
    memory: MemoryService,
    agent_name: str,
    *,
    from_token_address: str,
    to_token_address: str,
    from_token_symbol: str,
    to_token_symbol: str,
    amount_human: float,
    amount_raw: int,
) -> bool:
    """
    Perform a swap on Aerodrome Finance on Base.

    Aerodrome is the primary DEX on Base with deep liquidity for major pairs.
    """
    from ..aerodrome import try_aerodrome_swap_simulation, build_aerodrome_swap_tx

    w3: Web3 = ctx.web3
    wallet = to_checksum(w3, ctx.wallet_address)
    router_address = to_checksum(w3, AERODROME_ROUTER_ADDRESS)
    token_in = to_checksum(w3, from_token_address)
    token_out = to_checksum(w3, to_token_address)

    token_in_contract = w3.eth.contract(address=token_in, abi=ERC20_MINIMAL_ABI)

    # Log context
    _log_and_print(
        memory,
        ctx,
        agent_name,
        f"[LIVE] Preparing Aerodrome swap on router {router_address}: "
        f"{amount_human} {from_token_symbol} -> {to_token_symbol}.",
    )

    # 1) Try to simulate the swap first
    try:
        result = try_aerodrome_swap_simulation(
            w3, from_token_address, to_token_address, amount_raw, wallet
        )

        if not result:
            _log_and_print(
                memory,
                ctx,
                agent_name,
                f"No liquidity found on Aerodrome for {from_token_symbol}/{to_token_symbol}. "
                "Cannot execute swap.",
            )
            return False

        output_amount, routes = result
        _log_and_print(
            memory,
            ctx,
            agent_name,
            f"Found liquidity on Aerodrome! Expected output: {output_amount}",
        )

    except Exception as exc:  # noqa: BLE001
        _log_and_print(
            memory,
            ctx,
            agent_name,
            f"Error simulating Aerodrome swap: {exc!r}. Aborting.",
        )
        return False

    # 2) Check and handle allowance
    try:
        allowance = token_in_contract.functions.allowance(wallet, router_address).call()
    except Exception as exc:  # noqa: BLE001
        _log_and_print(
            memory,
            ctx,
            agent_name,
            f"Error fetching allowance for {from_token_symbol}: {exc!r}. Aborting swap.",
        )
        return False

    try:
        nonce = w3.eth.get_transaction_count(wallet, "pending")
    except Exception as exc:  # noqa: BLE001
        _log_and_print(
            memory,
            ctx,
            agent_name,
            f"Error fetching nonce for wallet {wallet}: {exc!r}. Aborting swap.",
        )
        return False

    gas_price = w3.eth.gas_price

    if allowance < amount_raw:
        _log_and_print(
            memory,
            ctx,
            agent_name,
            f"Current allowance for {from_token_symbol} is {allowance}, "
            f"needs to be at least {amount_raw}. Sending approval transaction...",
        )
        try:
            approve_tx = token_in_contract.functions.approve(
                router_address, amount_raw
            ).build_transaction(
                {
                    "from": wallet,
                    "nonce": nonce,
                    "gas": 200_000,
                    "gasPrice": gas_price,
                    "chainId": ctx.chain_id,
                }
            )
            signed_approve = w3.eth.account.sign_transaction(
                approve_tx, private_key=ctx.private_key
            )
            approve_hash = w3.eth.send_raw_transaction(signed_approve.raw_transaction)
            _log_and_print(
                memory,
                ctx,
                agent_name,
                f"Sent approve tx: {approve_hash.hex()}. Waiting for confirmation...",
            )
            approve_receipt = w3.eth.wait_for_transaction_receipt(approve_hash)
        except Exception as exc:  # noqa: BLE001
            _log_and_print(
                memory,
                ctx,
                agent_name,
                f"Approval transaction failed: {exc!r}. Aborting swap.",
            )
            return False

        if approve_receipt.status != 1:
            _log_and_print(
                memory,
                ctx,
                agent_name,
                f"Approval transaction reverted (status={approve_receipt.status}). Aborting swap.",
            )
            return False

        # Log approval success with BaseScan URL
        approve_hash_hex = approve_hash.hex() if hasattr(approve_hash, 'hex') else str(approve_hash)
        if not approve_hash_hex.startswith('0x'):
            approve_hash_hex = f'0x{approve_hash_hex}'
        approve_url = f"https://basescan.org/tx/{approve_hash_hex}"
        
        _log_and_print(
            memory,
            ctx,
            agent_name,
            f"Approval confirmed in block {approve_receipt.blockNumber}. "
            f"View on BaseScan: {approve_url}. Proceeding to swap...",
        )

        # Refresh nonce after approval
        try:
            nonce = w3.eth.get_transaction_count(wallet, "pending")
        except Exception as exc:  # noqa: BLE001
            _log_and_print(
                memory,
                ctx,
                agent_name,
                f"Error refreshing nonce after approval: {exc!r}. Aborting swap.",
            )
            return False

    # 3) Execute the swap
    deadline = int(time.time()) + 900  # 15 minutes

    try:
        swap_tx = build_aerodrome_swap_tx(
            w3,
            wallet,
            ctx.private_key,
            amount_raw,
            0,
            routes,
            deadline,  # 0 for amountOutMin (no slippage protection for now)
            nonce,
            gas_price,
            ctx.chain_id,
        )
        signed_swap = w3.eth.account.sign_transaction(
            swap_tx, private_key=ctx.private_key
        )
        swap_hash = w3.eth.send_raw_transaction(signed_swap.raw_transaction)
        _log_and_print(
            memory,
            ctx,
            agent_name,
            f"Sent Aerodrome swap tx: {swap_hash.hex()} "
            f"({amount_human} {from_token_symbol} -> {to_token_symbol}). "
            f"Waiting for confirmation...",
        )
        swap_receipt = w3.eth.wait_for_transaction_receipt(swap_hash)
    except Exception as exc:  # noqa: BLE001
        _log_and_print(
            memory,
            ctx,
            agent_name,
            f"Swap transaction failed: {exc!r}.",
        )
        return False

    if swap_receipt.status != 1:
        _log_and_print(
            memory,
            ctx,
            agent_name,
            f"Swap transaction reverted (status={swap_receipt.status}).",
        )
        return False

    # Log success with BaseScan URL for transaction tracking
    tx_hash_hex = swap_hash.hex() if hasattr(swap_hash, 'hex') else str(swap_hash)
    if not tx_hash_hex.startswith('0x'):
        tx_hash_hex = f'0x{tx_hash_hex}'
    basescan_url = f"https://basescan.org/tx/{tx_hash_hex}"
    
    _log_and_print(
        memory,
        ctx,
        agent_name,
        f"Swap confirmed! {amount_human} {from_token_symbol} -> {to_token_symbol} "
        f"in block {swap_receipt.blockNumber}. View on BaseScan: {basescan_url}",
    )
    return True


def run_update_generic(
    ctx: AgentContext,
    *,
    agent_name: str,
    ticker: str,
    quote_token: str,
    quote_symbol: str,
    api_key: str | None = None,
) -> None:
    """
    Shared update logic for SentiChain agents.
    """
    from ..auth import load_auth_config

    memory = ctx.memory

    # Resolve API key from argument or local auth config.
    key_to_use: str | None = api_key
    if not key_to_use:
        cfg = load_auth_config()
        if not cfg or not cfg.sentichain_api_key.strip():
            _log_and_print(
                memory,
                ctx,
                agent_name,
                "No SentiChain API key configured. "
                "Run `fundis auth` to set your API key before running agents.",
            )
            return
        key_to_use = cfg.sentichain_api_key.strip()

    try:
        events = fetch_sentichain_events(ticker, api_key=key_to_use)
    except Exception as exc:  # noqa: BLE001
        msg = f"Error fetching SentiChain data for {ticker}: {exc!r}. Skipping run."
        _log_and_print(memory, ctx, agent_name, msg)
        return

    _pretty_print_events(ctx, agent_name, events)
    counts = _sentiment_counts(events)
    bullish = counts.get("bullish", 0)
    bearish = counts.get("bearish", 0)
    _log_and_print(
        memory,
        ctx,
        agent_name,
        f"Sentiment counts for {ticker}: bullish={bullish}, bearish={bearish}.",
    )

    if bullish == 0 and bearish == 0:
        _log_and_print(
            memory,
            ctx,
            agent_name,
            "No bullish or bearish signals found. Skipping update.",
        )
        return

    if bullish == bearish:
        _log_and_print(
            memory,
            ctx,
            agent_name,
            "Bullish and bearish signals are equal. Skipping update.",
        )
        return

    pos = _ensure_allocation(ctx, agent_name, ticker, quote_token, memory)
    if not pos:
        return

    w3 = ctx.web3

    # Reconcile stored position with on-chain balances.
    try:
        usdc_human, usdc_raw, _ = get_erc20_balance(
            w3, USDC_ADDRESS, ctx.wallet_address
        )
        quote_human, quote_raw, _ = get_erc20_balance(
            w3, quote_token, ctx.wallet_address
        )
    except HTTPError as exc:
        _log_and_print(
            memory,
            ctx,
            agent_name,
            f"RPC error while reading balances: {exc}. Skipping update; try again later.",
        )
        return
    except Exception as exc:  # noqa: BLE001
        _log_and_print(
            memory,
            ctx,
            agent_name,
            f"Unexpected error while reading balances: {exc!r}. Skipping update.",
        )
        return

    side = pos.current_position
    if quote_raw <= 0 and side != "USDC":
        _log_and_print(
            memory,
            ctx,
            agent_name,
            f"On-chain {quote_symbol} balance is 0 (USDC balance={usdc_human}). "
            f"Resetting stored position from {side} to USDC.",
        )
        memory.update_position_side(ctx.wallet_address, agent_name, "USDC")
        side = "USDC"
    elif quote_raw > 0 and side != quote_symbol:
        _log_and_print(
            memory,
            ctx,
            agent_name,
            f"Detected on-chain {quote_symbol} balance ({quote_human}). "
            f"Resetting stored position from {side} to {quote_symbol}.",
        )
        memory.update_position_side(ctx.wallet_address, agent_name, quote_symbol)
        side = quote_symbol

    # Decision logic
    if bullish > bearish:
        if side == "USDC":
            # Long the asset: swap up to the allocated 10 USDC -> quote token
            msg = f"More bullish than bearish. Plan: LONG {ticker} (USDC -> {quote_symbol})."
            _log_and_print(memory, ctx, agent_name, msg)

            usdc_human, usdc_raw, usdc_info = get_erc20_balance(
                w3, USDC_ADDRESS, ctx.wallet_address
            )
            amount_raw = min(usdc_raw, pos.allocated_amount_raw)
            if amount_raw <= 0:
                _log_and_print(
                    memory,
                    ctx,
                    agent_name,
                    f"USDC balance is {usdc_human} {usdc_info.symbol}, nothing to swap.",
                )
                return
            amount_human = float(Decimal(amount_raw) / Decimal(10**usdc_info.decimals))

            ok = _perform_swap(
                ctx,
                memory,
                agent_name,
                from_token_address=USDC_ADDRESS,
                to_token_address=quote_token,
                from_token_symbol="USDC",
                to_token_symbol=quote_symbol,
                amount_human=amount_human,
                amount_raw=amount_raw,
            )
            if ok:
                memory.update_position_side(
                    ctx.wallet_address, agent_name, quote_symbol
                )
        else:
            _log_and_print(
                memory,
                ctx,
                agent_name,
                f"Already long {ticker} ({side}). Holding position.",
            )
    else:  # bearish > bullish
        if side == "USDC":
            _log_and_print(
                memory,
                ctx,
                agent_name,
                "More bearish than bullish, but already in USDC. Holding.",
            )
        else:
            msg = f"More bearish than bullish. Plan: EXIT {ticker} ({side} -> USDC)."
            _log_and_print(memory, ctx, agent_name, msg)

            quote_human, quote_raw, quote_info = get_erc20_balance(
                w3, quote_token, ctx.wallet_address
            )
            if quote_raw <= 0:
                _log_and_print(
                    memory,
                    ctx,
                    agent_name,
                    f"No {quote_symbol} balance to exit (balance={quote_human}).",
                )
                return

            amount_raw = quote_raw
            amount_human = float(quote_human)

            ok = _perform_swap(
                ctx,
                memory,
                agent_name,
                from_token_address=quote_token,
                to_token_address=USDC_ADDRESS,
                from_token_symbol=quote_symbol,
                to_token_symbol="USDC",
                amount_human=amount_human,
                amount_raw=amount_raw,
            )
            if ok:
                memory.update_position_side(ctx.wallet_address, agent_name, "USDC")


def run_unwind_generic(
    ctx: AgentContext,
    *,
    agent_name: str,
    ticker: str,
    quote_token: str,
    quote_symbol: str,
) -> None:
    """
    Shared unwind logic: move back to USDC regardless of sentiment.
    """
    memory = ctx.memory
    pos = memory.get_position(ctx.wallet_address, agent_name)
    if not pos:
        _log_and_print(
            memory,
            ctx,
            agent_name,
            "No existing position found for this agent and wallet. Nothing to unwind.",
        )
        return

    if pos.current_position == "USDC":
        _log_and_print(
            memory,
            ctx,
            agent_name,
            "Position already in USDC. Nothing to unwind.",
        )
        return

    w3 = ctx.web3

    try:
        quote_human, quote_raw, quote_info = get_erc20_balance(
            w3, quote_token, ctx.wallet_address
        )
    except HTTPError as exc:
        _log_and_print(
            memory,
            ctx,
            agent_name,
            f"RPC error while reading {quote_symbol} balance during unwind: {exc}. "
            "Skipping unwind; try again later.",
        )
        return
    except Exception as exc:  # noqa: BLE001
        _log_and_print(
            memory,
            ctx,
            agent_name,
            f"Unexpected error while reading {quote_symbol} balance during unwind: {exc!r}. "
            "Skipping unwind.",
        )
        return
    if quote_raw <= 0:
        _log_and_print(
            memory,
            ctx,
            agent_name,
            f"No {quote_symbol} balance to unwind (balance={quote_human}).",
        )
        # If there's truly no quote-token balance, treat stored position as USDC.
        if pos.current_position != "USDC":
            memory.update_position_side(ctx.wallet_address, agent_name, "USDC")
        return

    msg = (
        f"Unwinding position for {ticker}: {pos.current_position} "
        f"-> USDC for amount {quote_human}."
    )
    _log_and_print(memory, ctx, agent_name, msg)

    ok = _perform_swap(
        ctx,
        memory,
        agent_name,
        from_token_address=quote_token,
        to_token_address=USDC_ADDRESS,
        from_token_symbol=quote_symbol,
        to_token_symbol="USDC",
        amount_human=float(quote_human),
        amount_raw=quote_raw,
    )
    if ok:
        memory.update_position_side(ctx.wallet_address, agent_name, "USDC")

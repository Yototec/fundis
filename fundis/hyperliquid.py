"""
Hyperliquid perpetuals trading utilities.

This module provides helpers for interacting with Hyperliquid DEX
for perpetual futures trading.

Key concepts:
- Hyperliquid is a CLOB (Central Limit Order Book) perpetuals DEX
- Uses cross-margin by default (all positions share margin)
- Liquidation occurs when margin ratio drops below maintenance margin
- BTC has 3-5% initial margin (20-33x max leverage)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

import eth_account
from eth_account.signers.local import LocalAccount
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info

# Hyperliquid API endpoints
HYPERLIQUID_MAINNET_URL = "https://api.hyperliquid.xyz"
HYPERLIQUID_TESTNET_URL = "https://api.hyperliquid-testnet.xyz"

# Default leverage (1x = no leverage, just using margin as collateral)
DEFAULT_LEVERAGE = 1


@dataclass
class OrderResult:
    """Structured result from order execution."""

    success: bool
    filled_size: float
    avg_price: float
    status: str
    error: str | None = None
    raw_response: dict | None = None


@dataclass
class PositionInfo:
    """Current position information."""

    coin: str
    size: float  # Positive for long, negative for short
    entry_price: float
    unrealized_pnl: float
    liquidation_price: float | None
    margin_used: float
    leverage: float


def get_hyperliquid_info(testnet: bool = False) -> Info:
    """Get Hyperliquid Info client for reading data."""
    base_url = HYPERLIQUID_TESTNET_URL if testnet else HYPERLIQUID_MAINNET_URL
    return Info(base_url=base_url, skip_ws=True)


def get_hyperliquid_exchange(private_key: str, testnet: bool = False) -> Exchange:
    """
    Get Hyperliquid Exchange client for trading.

    Args:
        private_key: The private key of the wallet (can be the main wallet or agent wallet)
        testnet: Whether to use testnet (default: mainnet)

    Returns:
        Exchange client ready for trading
    """
    account: LocalAccount = eth_account.Account.from_key(private_key)
    base_url = HYPERLIQUID_TESTNET_URL if testnet else HYPERLIQUID_MAINNET_URL
    return Exchange(account, base_url=base_url)


def get_user_state(info: Info, wallet_address: str) -> dict:
    """
    Get the user's current state on Hyperliquid.

    Returns account summary including:
    - marginSummary: accountValue, totalMarginUsed, totalNtlPos, etc.
    - assetPositions: list of open positions
    """
    return info.user_state(wallet_address)


def get_position_for_coin(info: Info, wallet_address: str, coin: str) -> dict | None:
    """
    Get position info for a specific coin.

    Returns position dict with szi (signed size), entryPx, unrealizedPnl, etc.
    Returns None if no position exists.
    """
    state = info.user_state(wallet_address)
    for pos in state.get("assetPositions", []):
        position = pos.get("position", {})
        if position.get("coin") == coin:
            return position
    return None


def get_usdc_balance(info: Info, wallet_address: str) -> float:
    """
    Get the withdrawable USDC balance on Hyperliquid.

    This is the margin available for trading (after accounting for positions).
    """
    state = info.user_state(wallet_address)
    margin_summary = state.get("marginSummary", {})
    # accountValue is total value, withdrawable is available margin
    withdrawable = margin_summary.get("withdrawable", "0")
    return float(withdrawable)


def get_account_value(info: Info, wallet_address: str) -> float:
    """
    Get the total account value on Hyperliquid.
    """
    state = info.user_state(wallet_address)
    margin_summary = state.get("marginSummary", {})
    account_value = margin_summary.get("accountValue", "0")
    return float(account_value)


def market_open_long(
    exchange: Exchange,
    coin: str,
    size_usd: float,
    slippage: float = 0.01,
) -> dict:
    """
    Open a long position on a perpetual contract using a market order.

    Args:
        exchange: Hyperliquid Exchange client
        coin: The coin symbol (e.g., "BTC", "ETH")
        size_usd: The notional size in USD
        slippage: Slippage tolerance (default 1%)

    Returns:
        Order result dict from Hyperliquid
    """
    # Get current price for the coin to calculate size
    info = Info(base_url=exchange.base_url, skip_ws=True)
    all_mids = info.all_mids()

    mid_price = float(all_mids.get(coin, 0))
    if mid_price <= 0:
        raise ValueError(f"Could not get mid price for {coin}")

    # Calculate size in coin units
    size = size_usd / mid_price

    # Round size to appropriate decimals based on coin
    # BTC typically uses 4 decimal places, others may vary
    if coin == "BTC":
        size = round(size, 4)
    elif coin == "ETH":
        size = round(size, 3)
    else:
        size = round(size, 4)

    # Ensure minimum order size
    if size <= 0:
        raise ValueError(f"Order size too small: {size} {coin}")

    # Place market order (is_buy=True for long)
    result = exchange.market_open(
        coin=coin,
        is_buy=True,
        sz=size,
        slippage=slippage,
    )

    return result


def market_close_long(
    exchange: Exchange,
    coin: str,
    slippage: float = 0.01,
) -> dict:
    """
    Close an existing long position using a market order.

    Args:
        exchange: Hyperliquid Exchange client
        coin: The coin symbol (e.g., "BTC", "ETH")
        slippage: Slippage tolerance (default 1%)

    Returns:
        Order result dict from Hyperliquid
    """
    # Get current position
    info = Info(base_url=exchange.base_url, skip_ws=True)
    wallet_address = exchange.wallet.address

    position = get_position_for_coin(info, wallet_address, coin)
    if not position:
        raise ValueError(f"No open position found for {coin}")

    # szi is signed size: positive for long, negative for short
    szi = float(position.get("szi", 0))

    if szi <= 0:
        raise ValueError(f"No long position to close for {coin} (szi={szi})")

    # Close long by selling
    result = exchange.market_close(
        coin=coin,
        slippage=slippage,
    )

    return result


def get_all_open_positions(info: Info, wallet_address: str) -> list:
    """
    Get all open positions for a wallet.

    Returns list of position dicts with coin, szi, entryPx, unrealizedPnl, etc.
    """
    state = info.user_state(wallet_address)
    positions = []
    for pos in state.get("assetPositions", []):
        position = pos.get("position", {})
        szi = float(position.get("szi", 0))
        if szi != 0:  # Only include non-zero positions
            positions.append(position)
    return positions


def get_position_info(
    info: Info, wallet_address: str, coin: str
) -> PositionInfo | None:
    """
    Get detailed position information including liquidation price.

    Returns None if no position exists.
    """
    position = get_position_for_coin(info, wallet_address, coin)
    if not position:
        return None

    szi = float(position.get("szi", 0))
    if szi == 0:
        return None

    return PositionInfo(
        coin=coin,
        size=szi,
        entry_price=float(position.get("entryPx", 0)),
        unrealized_pnl=float(position.get("unrealizedPnl", 0)),
        liquidation_price=(
            float(position.get("liquidationPx"))
            if position.get("liquidationPx")
            else None
        ),
        margin_used=float(position.get("marginUsed", 0)),
        leverage=(
            float(position.get("leverage", {}).get("value", 1))
            if isinstance(position.get("leverage"), dict)
            else 1
        ),
    )


def get_margin_summary(info: Info, wallet_address: str) -> dict:
    """
    Get margin summary for the account.

    Returns:
        dict with keys:
        - account_value: Total account value (USDC)
        - total_margin_used: Margin used by positions
        - withdrawable: Available margin for new positions
        - margin_ratio: Used margin / Account value (lower is safer)
    """
    state = info.user_state(wallet_address)
    margin = state.get("marginSummary", {})

    account_value = float(margin.get("accountValue", 0))
    total_margin_used = float(margin.get("totalMarginUsed", 0))
    withdrawable = float(margin.get("withdrawable", 0))

    margin_ratio = total_margin_used / account_value if account_value > 0 else 0

    return {
        "account_value": account_value,
        "total_margin_used": total_margin_used,
        "withdrawable": withdrawable,
        "margin_ratio": margin_ratio,
    }


def check_can_open_position(
    info: Info,
    wallet_address: str,
    size_usd: float,
    leverage: int = DEFAULT_LEVERAGE,
) -> Tuple[bool, str]:
    """
    Check if we have enough margin to open a position.

    Args:
        info: Hyperliquid Info client
        wallet_address: Wallet address
        size_usd: Notional size in USD
        leverage: Leverage to use (default 1x)

    Returns:
        (can_open: bool, reason: str)
    """
    margin_summary = get_margin_summary(info, wallet_address)
    withdrawable = margin_summary["withdrawable"]

    # Required margin = notional / leverage
    # At 1x leverage, need full notional as margin
    required_margin = size_usd / leverage

    # Add 10% buffer for safety
    required_with_buffer = required_margin * 1.1

    if withdrawable < required_with_buffer:
        return False, (
            f"Insufficient margin: have ${withdrawable:.2f} available, "
            f"need ~${required_with_buffer:.2f} (${required_margin:.2f} + 10% buffer) "
            f"for ${size_usd:.2f} position at {leverage}x leverage"
        )

    return True, f"OK: ${withdrawable:.2f} available, need ${required_with_buffer:.2f}"


def set_leverage(exchange: Exchange, coin: str, leverage: int) -> dict:
    """
    Set leverage for a coin. Must be called before opening position if not using default.

    Args:
        exchange: Hyperliquid Exchange client
        coin: Coin symbol (e.g., "BTC")
        leverage: Leverage value (1-50 depending on coin)

    Returns:
        Result dict from Hyperliquid
    """
    return exchange.update_leverage(leverage, coin, is_cross=True)


def parse_order_result(result: dict) -> OrderResult:
    """
    Parse the raw order result from Hyperliquid into a structured format.

    Hyperliquid returns:
    {
        "status": "ok" | "err",
        "response": {
            "type": "order",
            "data": {
                "statuses": [
                    {"filled": {"totalSz": "0.001", "avgPx": "95000"}}
                    OR {"error": "..."}
                    OR {"resting": {"oid": 123}}  # Partially filled, rest is resting
                ]
            }
        }
    }
    """
    status = result.get("status", "")
    response = result.get("response", {})

    if status != "ok":
        return OrderResult(
            success=False,
            filled_size=0,
            avg_price=0,
            status=status,
            error=str(response),
            raw_response=result,
        )

    data = response.get("data", {})
    statuses = data.get("statuses", [])

    if not statuses:
        return OrderResult(
            success=False,
            filled_size=0,
            avg_price=0,
            status="no_statuses",
            error="No order statuses returned",
            raw_response=result,
        )

    first_status = statuses[0]

    # Check for error
    if "error" in first_status:
        return OrderResult(
            success=False,
            filled_size=0,
            avg_price=0,
            status="error",
            error=first_status["error"],
            raw_response=result,
        )

    # Check for fill
    if "filled" in first_status:
        filled = first_status["filled"]
        return OrderResult(
            success=True,
            filled_size=float(filled.get("totalSz", 0)),
            avg_price=float(filled.get("avgPx", 0)),
            status="filled",
            raw_response=result,
        )

    # Check for resting (partial fill or limit order waiting)
    if "resting" in first_status:
        return OrderResult(
            success=True,  # Order accepted but not fully filled
            filled_size=0,  # Resting means not filled yet
            avg_price=0,
            status="resting",
            error="Order resting in book (not immediately filled)",
            raw_response=result,
        )

    return OrderResult(
        success=False,
        filled_size=0,
        avg_price=0,
        status="unknown",
        error=f"Unknown status format: {first_status}",
        raw_response=result,
    )


def market_open_long_safe(
    exchange: Exchange,
    coin: str,
    size_usd: float,
    slippage: float = 0.02,  # 2% slippage for safety
    leverage: int = DEFAULT_LEVERAGE,
) -> OrderResult:
    """
    Safely open a long position with proper checks and error handling.

    This function:
    1. Checks margin availability
    2. Gets current price
    3. Places market order with slippage protection
    4. Parses and returns structured result

    Args:
        exchange: Hyperliquid Exchange client
        coin: The coin symbol (e.g., "BTC", "ETH")
        size_usd: The notional size in USD
        slippage: Slippage tolerance (default 2% for market orders)
        leverage: Leverage to use (default 1x = no leverage)

    Returns:
        OrderResult with success status, fill info, or error details
    """
    info = Info(base_url=exchange.base_url, skip_ws=True)
    wallet_address = exchange.wallet.address

    # 1. Check margin
    can_open, reason = check_can_open_position(info, wallet_address, size_usd, leverage)
    if not can_open:
        return OrderResult(
            success=False,
            filled_size=0,
            avg_price=0,
            status="margin_check_failed",
            error=reason,
        )

    # 2. Get current price
    all_mids = info.all_mids()
    mid_price = float(all_mids.get(coin, 0))
    if mid_price <= 0:
        return OrderResult(
            success=False,
            filled_size=0,
            avg_price=0,
            status="price_error",
            error=f"Could not get mid price for {coin}",
        )

    # 3. Calculate size
    size = size_usd / mid_price

    # Round to appropriate precision
    if coin == "BTC":
        size = round(size, 4)
    elif coin == "ETH":
        size = round(size, 3)
    else:
        size = round(size, 4)

    if size <= 0:
        return OrderResult(
            success=False,
            filled_size=0,
            avg_price=0,
            status="size_error",
            error=f"Order size too small: {size} {coin} (${size_usd} / ${mid_price})",
        )

    # 4. Place market order
    try:
        result = exchange.market_open(
            coin=coin,
            is_buy=True,
            sz=size,
            slippage=slippage,
        )
        return parse_order_result(result)
    except Exception as exc:
        return OrderResult(
            success=False,
            filled_size=0,
            avg_price=0,
            status="exception",
            error=str(exc),
        )


def market_close_long_safe(
    exchange: Exchange,
    coin: str,
    slippage: float = 0.02,
) -> OrderResult:
    """
    Safely close a long position with proper error handling.

    Returns:
        OrderResult with success status, fill info, or error details
    """
    info = Info(base_url=exchange.base_url, skip_ws=True)
    wallet_address = exchange.wallet.address

    # Check if we have a position to close
    position = get_position_for_coin(info, wallet_address, coin)
    if not position:
        return OrderResult(
            success=True,  # Not an error - just nothing to close
            filled_size=0,
            avg_price=0,
            status="no_position",
            error=f"No open position found for {coin}",
        )

    szi = float(position.get("szi", 0))
    if szi <= 0:
        return OrderResult(
            success=True,
            filled_size=0,
            avg_price=0,
            status="no_long_position",
            error=f"No long position to close (szi={szi})",
        )

    try:
        result = exchange.market_close(
            coin=coin,
            slippage=slippage,
        )
        return parse_order_result(result)
    except Exception as exc:
        return OrderResult(
            success=False,
            filled_size=0,
            avg_price=0,
            status="exception",
            error=str(exc),
        )


def check_liquidation_risk(
    info: Info,
    wallet_address: str,
    coin: str,
) -> Tuple[bool, str]:
    """
    Check if a position is at risk of liquidation.

    Returns:
        (at_risk: bool, message: str)
    """
    pos_info = get_position_info(info, wallet_address, coin)
    if not pos_info:
        return False, "No position"

    if not pos_info.liquidation_price:
        return False, "No liquidation price (position may be fully collateralized)"

    # Get current price
    all_mids = info.all_mids()
    current_price = float(all_mids.get(coin, 0))

    if current_price <= 0:
        return True, "Cannot determine current price"

    liq_price = pos_info.liquidation_price

    # For long positions, liquidation happens when price drops
    if pos_info.size > 0:
        distance_pct = (current_price - liq_price) / current_price * 100
        if distance_pct < 5:  # Within 5% of liquidation
            return True, (
                f"WARNING: Long position at risk! "
                f"Current: ${current_price:.2f}, Liq: ${liq_price:.2f} "
                f"({distance_pct:.1f}% away)"
            )
        return False, (
            f"Long position OK. Current: ${current_price:.2f}, "
            f"Liq: ${liq_price:.2f} ({distance_pct:.1f}% away)"
        )

    # For short positions, liquidation happens when price rises
    else:
        distance_pct = (liq_price - current_price) / current_price * 100
        if distance_pct < 5:
            return True, (
                f"WARNING: Short position at risk! "
                f"Current: ${current_price:.2f}, Liq: ${liq_price:.2f} "
                f"({distance_pct:.1f}% away)"
            )
        return False, (
            f"Short position OK. Current: ${current_price:.2f}, "
            f"Liq: ${liq_price:.2f} ({distance_pct:.1f}% away)"
        )

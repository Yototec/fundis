from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Tuple
import time

from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

from .config import BASE_RPC_URL


PUBLIC_RPC_THROTTLE_SECONDS = 0.5


ERC20_MINIMAL_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "symbol",
        "outputs": [{"name": "", "type": "string"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [
            {"name": "_owner", "type": "address"},
            {"name": "_spender", "type": "address"},
        ],
        "name": "allowance",
        "outputs": [{"name": "remaining", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_spender", "type": "address"},
            {"name": "_value", "type": "uint256"},
        ],
        "name": "approve",
        "outputs": [{"name": "success", "type": "bool"}],
        "type": "function",
    },
]


@dataclass
class TokenInfo:
    address: str
    decimals: int
    symbol: str


def get_web3() -> Web3:
    """
    Build a Web3 instance configured for Base mainnet.
    """
    # Determine RPC URL: prefer a premium endpoint from auth config, if present.
    rpc_url = BASE_RPC_URL
    try:
        # Local import to avoid circular dependency at module import time.
        from .auth import load_auth_config

        cfg = load_auth_config()
        if cfg and cfg.premium_base_rpc_url:
            rpc_url = cfg.premium_base_rpc_url
    except Exception:  # noqa: BLE001
        # Fall back to the public endpoint on any error.
        rpc_url = BASE_RPC_URL

    provider = Web3.HTTPProvider(rpc_url)
    w3 = Web3(provider)
    # Attach metadata for downstream helpers (e.g. throttling).
    try:
        w3._fundis_rpc_url = rpc_url  # type: ignore[attr-defined]
        w3._fundis_is_public_rpc = rpc_url == BASE_RPC_URL  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass

    # Base is an OP-stack chain (PoA-like header); inject the PoA extraData middleware.
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    return w3


def to_checksum(w3: Web3, address: str) -> str:
    return w3.to_checksum_address(address)


def get_erc20_token_info(w3: Web3, token_address: str) -> TokenInfo:
    contract = w3.eth.contract(
        address=to_checksum(w3, token_address), abi=ERC20_MINIMAL_ABI
    )
    decimals = contract.functions.decimals().call()
    symbol = contract.functions.symbol().call()
    return TokenInfo(address=contract.address, decimals=decimals, symbol=symbol)


def get_erc20_balance(
    w3: Web3, token_address: str, wallet_address: str
) -> Tuple[Decimal, int, TokenInfo]:
    """
    Returns (human_amount, raw_amount, token_info).
    """
    # When using the public Base RPC, add a small delay to reduce the chance of
    # hitting rate limits (429 errors). Premium RPC endpoints are used as-is.
    is_public = getattr(w3, "_fundis_is_public_rpc", False)
    if is_public and PUBLIC_RPC_THROTTLE_SECONDS > 0:
        time.sleep(PUBLIC_RPC_THROTTLE_SECONDS)

    info = get_erc20_token_info(w3, token_address)
    contract = w3.eth.contract(address=info.address, abi=ERC20_MINIMAL_ABI)
    raw = contract.functions.balanceOf(to_checksum(w3, wallet_address)).call()
    human = Decimal(raw) / Decimal(10**info.decimals)
    return human, raw, info

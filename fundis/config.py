from __future__ import annotations

from pathlib import Path


APP_NAME = "fundis"


def get_data_dir() -> Path:
    """
    Returns the base directory for all local data (wallets, memory DB, etc.).

    We intentionally avoid environment-variable configuration here and always
    use a deterministic path under the user's home directory.
    """
    return Path.home() / f".{APP_NAME}"


DATA_DIR: Path = get_data_dir()
WALLET_STORE_PATH: Path = DATA_DIR / "wallets.json"
MEMORY_DB_PATH: Path = DATA_DIR / "memory.db"

# Arbitrum chain configuration (for Hyperliquid deposits/withdrawals)
ARBITRUM_CHAIN_ID: int = 42161
ARBITRUM_RPC_URL: str = "https://arb1.arbitrum.io/rpc"

# Token addresses on Arbitrum
ARBITRUM_USDC_ADDRESS = (
    "0xaf88d065e77c8cC2239327C5EDb3A432268e5831"  # Native USDC on Arbitrum
)

# Hyperliquid configuration
# Default allocation for Hyperliquid perpetuals agents (in USD)
HYPERLIQUID_ALLOCATION_USD: float = 10.0

# Hyperliquid Bridge on Arbitrum
# This is the official deposit contract for bridging USDC from Arbitrum to Hyperliquid
HYPERLIQUID_BRIDGE_ADDRESS = "0x2Df1c51E09aECF9cacB7bc98cB1742757f163dF7"


def ensure_data_dir() -> None:
    """Ensure that the data directory exists."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

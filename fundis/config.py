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

# Base chain configuration (hard-coded for Base mainnet)
BASE_CHAIN_ID: int = 8453
BASE_RPC_URL: str = "https://mainnet.base.org"

# Token addresses on Base (as plain strings; converted to checksum addresses by web3 helpers)
USDC_ADDRESS = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
WBTC_ADDRESS = "0x0555E30da8f98308EdB960aa94C0Db47230d2B9c"
WETH_ADDRESS = "0x4200000000000000000000000000000000000006"

# Uniswap v3 contracts on Base (from official deployments)
# https://docs.uniswap.org/contracts/v3/reference/deployments/base-deployments
UNISWAP_V3_SWAP_ROUTER_ADDRESS = "0x2626664c2603336E57B271c5C0b26F421741e481"
UNISWAP_V3_FEE_TIER = 3000  # 0.3% pool


def ensure_data_dir() -> None:
    """Ensure that the data directory exists."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)


# Fundis

Web3 trading agents powered by SentiChain sentiment data.

## Overview

Fundis is a Python CLI tool for running automated trading agents that make decisions based on real-time sentiment analysis from [SentiChain](https://sentichain.com/). Agents can execute:

- **Spot swaps** on Base network via Aerodrome Finance
- **Perpetual futures** on Hyperliquid DEX

## Features

- **Sentiment-Based Trading**: Agents automatically trade based on bullish/bearish sentiment from SentiChain
- **Multi-Chain Support**: Trade on Base (spot) and Hyperliquid (perpetuals)
- **Perpetuals Trading**: Open/close BTC long positions on Hyperliquid with margin monitoring
- **Bridge & Swap**: Built-in tools to move USDC between Arbitrum and Hyperliquid
- **Customizable Allocations**: Set your own allocation per agent (default 10 USDC)
- **Smart Execution**: Uses `min(balance, allocation)` to prevent transaction failures
- **Local Wallet Management**: Secure local storage of wallet keys
- **Position Tracking**: SQLite-based memory system tracks positions and trade history
- **Historical Logs**: Query past agent communications and decisions
- **Simple CLI Interface**: Interactive menus for all operations

## Installation

### From PyPI (Recommended)

```bash
pip install fundis
```

### From Source

```bash
git clone https://github.com/Yototec/fundis.git
cd fundis
pip install -e .
```

## Quick Start

### 1. Set up your SentiChain API key

```bash
fundis auth
```

Get your API key from [SentiChain](https://sentichain.com/)

### 2. Import a wallet

```bash
fundis wallet
```

Import an EVM private key with funds on the relevant network.

### 3. Run an agent

```bash
fundis agent
```

Choose an agent, select your wallet, and set your allocation amount.

## Available Agents

| Agent | Network | Type | Action |
|-------|---------|------|--------|
| **SentiChain ETH Agent on Base** | Base | Spot | Swaps USDC ↔ WETH |
| **SentiChain BTC Agent on Base** | Base | Spot | Swaps USDC ↔ WBTC |
| **SentiChain BTC Agent on Hyperliquid** | Hyperliquid | Perpetuals | Opens/closes BTC long positions |

## Trading Logic

Each agent:
1. Fetches latest sentiment events from SentiChain API
2. Counts bullish vs bearish signals
3. Makes trading decisions:
   - **More bullish → Long** (buy asset or open long)
   - **More bearish → Exit** (sell asset or close position)
   - **Equal signals → Hold** current position

### Allocation System

- **Customizable**: Set any USDC amount when first running an agent
- **Default**: 10 USDC if not specified
- **Smart execution**: Trades `min(available_balance, allocation)` to prevent failures
- **Persistent**: Allocation is stored per agent/wallet pair

Example: Set 100 USDC allocation but only have 50 USDC → trades 50 USDC. Later get 80 USDC → trades 80 USDC. Get 150 USDC → trades 100 USDC (capped).

## Commands

### Wallet Management
```bash
fundis wallet
```
- List wallets
- Import wallet (private key)
- Export wallet
- Delete wallet

### API Key Management
```bash
fundis auth
```
- Set SentiChain API key
- Configure premium RPC URL (optional)
- Show current configuration
- Delete stored keys

### Agent Operations
```bash
fundis agent
```
- Select agent
- Choose wallet
- Set allocation (first run or after unwind)
- Update agent (run trading logic once)
- Unwind agent (return to USDC/flat)
- View current allocation

### Bridge & Swap (Swidge)
```bash
fundis swidge
```
- Deposit USDC from Arbitrum to Hyperliquid
- Withdraw USDC from Hyperliquid to Arbitrum
- Check Hyperliquid balance
- Check Arbitrum balances

### Historical Logs
```bash
fundis logs
```
- View recent logs (all agents)
- View logs by agent
- View logs by wallet
- Search logs by keyword
- View log statistics
- Clear logs

## Network Configuration

### Base Network (Spot Trading)
- **Chain ID**: 8453
- **DEX**: Aerodrome Finance
- **Tokens**:
  - USDC: `0x833589fcd6edb6e08f4c7c32d4f71b54bda02913`
  - WETH: `0x4200000000000000000000000000000000000006`
  - WBTC: `0x0555E30da8f98308EdB960aa94C0Db47230d2B9c`

### Hyperliquid (Perpetuals Trading)
- **Deposit Network**: Arbitrum (Chain ID: 42161)
- **Bridge Contract**: `0x2Df1c51E09aECF9cacB7bc98cB1742757f163dF7`
- **Collateral**: USDC
- **Available Pairs**: BTC-PERP (more coming)

### Arbitrum (Bridge)
- **Chain ID**: 42161
- **USDC**: `0xaf88d065e77c8cC2239327C5EDb3A432268e5831`

## Hyperliquid Agent Features

The Hyperliquid perpetuals agent includes:

- **Margin Checking**: Validates available margin before opening positions
- **Liquidation Monitoring**: Warns if position is within 5% of liquidation price
- **Position Reconciliation**: Detects if positions were liquidated or manually closed
- **Safe Order Execution**: Uses 2% slippage tolerance for market orders
- **Structured Results**: Clear success/failure status with fill details

## Data Storage

All data is stored locally in `~/.fundis/`:
- `wallets.json` - Wallet storage
- `memory.db` - SQLite database for positions and logs
- `auth.json` - API keys and RPC configuration

## Security Considerations

**Important Security Notes**:
- Private keys are stored locally (use at your own risk)
- Only use wallets you're comfortable with for testing
- Start with small amounts to test the system
- Perpetuals trading carries liquidation risk
- This is alpha software - bugs may exist
- Max approval is used for gas efficiency (revoke manually if needed)

## Requirements

- Python 3.10+
- For Base agents:
  - Wallet with USDC on Base
  - ETH on Base for gas
- For Hyperliquid agents:
  - USDC deposited on Hyperliquid (via Arbitrum bridge)
  - ETH on Arbitrum for bridge gas

## Development

```bash
# Clone the repository
git clone https://github.com/Yototec/fundis.git
cd fundis

# Install in development mode with test dependencies
pip install -e ".[dev]"
```

## Testing

The test suite includes unit tests (no network) and integration tests (real network).

```bash
# Run all safe tests (no transactions)
python tests/run_tests.py all-safe

# Run specific test categories
python tests/run_tests.py unit       # Unit tests only (no network)
python tests/run_tests.py connect    # Test network connections
python tests/run_tests.py balance    # Check balances on all networks
python tests/run_tests.py summary    # Print wallet summary
python tests/run_tests.py logs       # Test logging functionality

# Run with pytest directly
pytest tests/test_unit.py -v              # Unit tests
pytest tests/test_integration.py -v -s    # Integration tests
```

### Test Prerequisites

For integration tests:
1. Import a wallet: `fundis wallet`
2. Set SentiChain API key: `fundis auth`
3. Have small amounts on relevant networks for balance checks

### Real Transaction Tests

Transaction tests are disabled by default. To enable, edit `tests/test_integration.py` and change `@pytest.mark.skipif(True, ...)` to `@pytest.mark.skipif(False, ...)` for the specific test.

## Dependencies

- `typer` - CLI framework
- `web3` - Ethereum interaction
- `hyperliquid-python-sdk` - Hyperliquid DEX integration
- `requests` - HTTP client

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

MIT License - see [LICENSE](LICENSE) file for details

## Disclaimer

This software is for educational purposes. Trading cryptocurrencies and perpetual futures carries significant risk, including the risk of liquidation. Users are responsible for their own trading decisions and should not rely solely on automated systems. Always do your own research and never invest more than you can afford to lose.

## Support

- GitHub Issues: [github.com/yototec/fundis/issues](https://github.com/yototec/fundis/issues)
- SentiChain: [sentichain.com](https://sentichain.com/)

## Acknowledgments

- [SentiChain](https://sentichain.com/) for sentiment data
- [Aerodrome Finance](https://aerodrome.finance/) for Base DEX infrastructure
- [Hyperliquid](https://hyperliquid.xyz/) for perpetuals trading
- Base network for low-cost EVM execution

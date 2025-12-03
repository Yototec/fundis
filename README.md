# Fundis

Web3 trading agents powered by SentiChain sentiment data.

## Overview

Fundis is a Python CLI tool for running automated trading agents that make decisions based on real-time trading signals from [SentiChain](https://sentichain.com/). Agents execute **perpetual futures** trades on Hyperliquid DEX.

## Features

- **Signal-Based Trading**: Agents trade based on LONG/SHORT signals from SentiChain's AI analysis
- **Research Notes**: Full research reports available for transparency on trading decisions
- **Perpetuals Trading**: Open/close BTC and ETH long positions on Hyperliquid
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

Import an EVM private key.

### 3. Deposit USDC to Hyperliquid

```bash
fundis swidge
```

Bridge USDC from Arbitrum to Hyperliquid (you need USDC + ETH on Arbitrum).

### 4. Run an agent

```bash
fundis agent
```

Choose an agent, select your wallet, and set your allocation amount.

## Available Agents

| Agent | Asset | Type | Action |
|-------|-------|------|--------|
| **SentiChain BTC Agent on Hyperliquid** | BTC | Perpetuals | Long-only trading based on signals |
| **SentiChain ETH Agent on Hyperliquid** | ETH | Perpetuals | Long-only trading based on signals |

## Trading Logic

Each agent is **long-only** and uses SentiChain's trading signals:

1. Fetches latest trading signal from SentiChain API (`product_trading_signal`)
2. Fetches research note for logging/display (`product_research_note`)
3. Makes trading decisions:
   - **LONG signal → Open long** (if currently FLAT)
   - **SHORT signal → Close long** (go to FLAT)
   - **Already in correct position → Hold**

### Trading Signal Structure

The SentiChain API provides structured signals with:
- **Direction**: LONG or SHORT
- **Confidence**: 0-100% confidence level
- **Strength**: WEAK, MODERATE, or STRONG
- **Conviction Score**: 1-10 rating
- **Risk Rating**: LOW, MEDIUM, or HIGH
- **Entry/Exit Conditions**: Specific price levels and conditions
- **Timeframe**: Expected duration

### Research Notes

Each signal is accompanied by a research note containing:
- Executive summary and investment thesis
- Bull/bear case scenarios with probabilities
- Key catalysts to watch
- Risk factors and contrarian views

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
- Unwind agent (return to FLAT)
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

### Hyperliquid (Perpetuals Trading)
- **Deposit Network**: Arbitrum (Chain ID: 42161)
- **Bridge Contract**: `0x2Df1c51E09aECF9cacB7bc98cB1742757f163dF7`
- **Collateral**: USDC
- **Available Pairs**: BTC-PERP, ETH-PERP

### Arbitrum (Bridge)
- **Chain ID**: 42161
- **USDC**: `0xaf88d065e77c8cC2239327C5EDb3A432268e5831`

## Hyperliquid Agent Features

The Hyperliquid perpetuals agents include:

- **Margin Checking**: Validates available margin before opening positions
- **Liquidation Monitoring**: Warns if position is within 5% of liquidation price
- **Position Reconciliation**: Detects if positions were liquidated or manually closed
- **Safe Order Execution**: Uses 2% slippage tolerance for market orders
- **Structured Results**: Clear success/failure status with fill details

## SentiChain API Integration

The agents use two SentiChain API endpoints:

### Trading Signal
```
GET https://api.sentichain.com/agent/get_reasoning_last
    ?ticker={BTC|ETH}
    &summary_type=product_trading_signal
    &api_key={your_api_key}
```

Returns structured JSON with trading direction, confidence, and risk parameters.

### Research Note
```
GET https://api.sentichain.com/agent/get_reasoning_last
    ?ticker={BTC|ETH}
    &summary_type=product_research_note
    &api_key={your_api_key}
```

Returns markdown-formatted research report with detailed analysis.

## Data Storage

All data is stored locally in `~/.fundis/`:
- `wallets.json` - Wallet storage
- `memory.db` - SQLite database for positions and logs
- `auth.json` - API key configuration

## Security Considerations

**Important Security Notes**:
- Private keys are stored locally (use at your own risk)
- Only use wallets you're comfortable with for testing
- Start with small amounts to test the system
- Perpetuals trading carries liquidation risk
- This is alpha software - bugs may exist

## Requirements

- Python 3.10+
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
- `hyperliquid-python-sdk` - Hyperliquid DEX integration
- `web3` - Ethereum interaction (for Arbitrum bridge)
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

- [SentiChain](https://sentichain.com/) for AI-powered trading signals and research
- [Hyperliquid](https://hyperliquid.xyz/) for perpetuals trading infrastructure

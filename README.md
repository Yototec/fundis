# Fundis

Web3 trading agents powered by SentiChain sentiment data on Base network.

## Overview

Fundis is a Python CLI tool for running automated trading agents that make decisions based on real-time sentiment analysis from [SentiChain](https://sentichain.com/). The agents trade on Base network using Aerodrome Finance, the primary DEX on Base.

## Features

- **Sentiment-Based Trading**: Agents automatically trade based on bullish/bearish sentiment from SentiChain
- **Real On-Chain Execution**: Live trading on Base network via Aerodrome Finance
- **Local Wallet Management**: Secure local storage of wallet keys
- **Position Tracking**: SQLite-based memory system tracks positions and trade history
- **Simple CLI Interface**: Interactive menus for wallet, auth, and agent management

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

Import an EVM private key (with USDC funds on Base network)

### 3. Run an agent

```bash
fundis agent
```

Choose an agent (ETH or BTC) and select "Update agent" to execute trades

## Available Agents

- **SentiChain ETH Agent**: Trades USDC ↔ WETH based on Ethereum sentiment
- **SentiChain BTC Agent**: Trades USDC ↔ WBTC based on Bitcoin sentiment

## Trading Logic

Each agent:
1. Fetches latest sentiment events from SentiChain API
2. Counts bullish vs bearish signals
3. Makes trading decisions:
   - **More bullish → Buy** (USDC → WETH/WBTC)
   - **More bearish → Sell** (WETH/WBTC → USDC)
   - **Equal signals → Hold** current position

Agents manage a fixed allocation of **10 USDC** per wallet.

## Network Configuration

- **Network**: Base (Chain ID: 8453)
- **DEX**: Aerodrome Finance
- **Tokens**:
  - USDC: `0x833589fcd6edb6e08f4c7c32d4f71b54bda02913`
  - WETH: `0x4200000000000000000000000000000000000006`
  - WBTC: `0x0555E30da8f98308EdB960aa94C0Db47230d2B9c`

## Commands

### Wallet Management
```bash
fundis wallet
```
- Import wallet (private key)
- Export wallet
- Delete wallet
- List wallets

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
- Select agent (ETH or BTC)
- Choose wallet
- Update agent (run trading logic once)
- Unwind agent (return to USDC)

## Data Storage

All data is stored locally in `~/.fundis/`:
- `wallets.json` - Encrypted wallet storage
- `memory.db` - SQLite database for positions and logs
- `auth.json` - API keys and RPC configuration

## Security Considerations

**Important Security Notes**:
- Private keys are stored locally (use at your own risk)
- Only use wallets you're comfortable with for testing
- Start with small amounts to test the system
- This is alpha software - bugs may exist

## Requirements

- Python 3.10+
- Base network wallet with:
  - At least 10 USDC for trading
  - ETH for gas fees

## Development

```bash
# Clone the repository
git clone https://github.com/Yototec/fundis.git
cd fundis

# Install in development mode
pip install -e .

# Run tests (if available)
pytest
```

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

MIT License - see [LICENSE](LICENSE) file for details

## Disclaimer

This software is for educational purposes. Trading cryptocurrencies carries significant risk. Users are responsible for their own trading decisions and should not rely solely on automated systems. Always do your own research and never invest more than you can afford to lose.

## Support

- GitHub Issues: [github.com/yototec/fundis/issues](https://github.com/yototec/fundis/issues)
- SentiChain: [sentichain.com](https://sentichain.com/)

## Acknowledgments

- [SentiChain](https://sentichain.com/) for sentiment data
- [Aerodrome Finance](https://aerodrome.finance/) for DEX infrastructure
- Base network for low-cost EVM execution
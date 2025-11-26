"""
Integration tests for Fundis - Uses REAL wallet and transactions.

IMPORTANT: These tests use real funds! Each test is limited to 1 USDC max.

Prerequisites:
1. Have a wallet imported via `fundis wallet`
2. Have SentiChain API key set via `fundis auth`
3. Have USDC on Base network (for Base agents)
4. Have USDC on Hyperliquid (for Hyperliquid agent)
5. Have USDC + ETH on Arbitrum (for bridge tests)

Run with: pytest tests/test_integration.py -v -s
The -s flag shows print output for monitoring real transactions.

To run specific test categories:
    pytest tests/test_integration.py -v -s -k "base"       # Base network tests
    pytest tests/test_integration.py -v -s -k "hyperliquid" # Hyperliquid tests
    pytest tests/test_integration.py -v -s -k "bridge"     # Bridge tests
"""

import pytest
import time
from decimal import Decimal

# Test allocation - KEEP THIS LOW for safety!
TEST_ALLOCATION_USDC = 1.0


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def wallet_store():
    """Get wallet store with at least one wallet."""
    from fundis.wallets import WalletStore

    store = WalletStore()
    if not store.wallets:
        pytest.skip("No wallets configured. Run `fundis wallet` first.")
    return store


@pytest.fixture
def first_wallet(wallet_store):
    """Get the first configured wallet."""
    return wallet_store.get_wallet(0)


@pytest.fixture
def memory_service():
    """Get memory service."""
    from fundis.memory import MemoryService

    return MemoryService()


@pytest.fixture
def auth_config():
    """Get auth config with API key."""
    from fundis.auth import load_auth_config

    cfg = load_auth_config()
    if not cfg or not cfg.sentichain_api_key:
        pytest.skip("No SentiChain API key configured. Run `fundis auth` first.")
    return cfg


# ============================================================================
# Connection Tests (No transactions)
# ============================================================================


class TestConnections:
    """Test network connections without transactions."""

    def test_base_rpc_connection(self):
        """Test Base RPC connection."""
        from fundis.web3_utils import get_web3

        w3 = get_web3()
        assert w3.is_connected(), "Failed to connect to Base RPC"
        chain_id = w3.eth.chain_id
        assert chain_id == 8453, f"Expected Base chain ID 8453, got {chain_id}"
        print(f"✓ Connected to Base (chain ID: {chain_id})")

    def test_arbitrum_rpc_connection(self):
        """Test Arbitrum RPC connection."""
        from fundis.swidge import get_arbitrum_web3

        w3 = get_arbitrum_web3()
        assert w3.is_connected(), "Failed to connect to Arbitrum RPC"
        chain_id = w3.eth.chain_id
        assert chain_id == 42161, f"Expected Arbitrum chain ID 42161, got {chain_id}"
        print(f"✓ Connected to Arbitrum (chain ID: {chain_id})")

    def test_hyperliquid_connection(self):
        """Test Hyperliquid API connection."""
        from fundis.hyperliquid import get_hyperliquid_info

        info = get_hyperliquid_info()
        # Try to get all mids (prices) - this validates connection
        mids = info.all_mids()
        assert "BTC" in mids, "BTC not found in Hyperliquid markets"
        btc_price = float(mids["BTC"])
        assert btc_price > 0, "Invalid BTC price"
        print(f"✓ Connected to Hyperliquid (BTC price: ${btc_price:,.2f})")

    def test_sentichain_api(self, auth_config):
        """Test SentiChain API connection."""
        import requests

        url = (
            "https://api.sentichain.com/agent/get_reasoning_last"
            f"?ticker=BTC&summary_type=l3_event_sentiment_reasoning"
            f"&api_key={auth_config.sentichain_api_key}"
        )
        resp = requests.get(url, timeout=10)
        assert resp.status_code == 200, f"SentiChain API error: {resp.status_code}"
        data = resp.json()
        assert "reasoning" in data, "Invalid SentiChain response"
        print("✓ Connected to SentiChain API")


# ============================================================================
# Balance Check Tests (No transactions)
# ============================================================================


class TestBalances:
    """Test balance checking on various networks."""

    def test_base_usdc_balance(self, first_wallet):
        """Check USDC balance on Base."""
        from fundis.web3_utils import get_web3, get_erc20_balance
        from fundis.config import USDC_ADDRESS

        w3 = get_web3()
        human, raw, info = get_erc20_balance(w3, USDC_ADDRESS, first_wallet.address)
        print(f"✓ Base USDC balance: {human} {info.symbol}")
        assert info.symbol == "USDC"
        return float(human)

    def test_base_eth_balance(self, first_wallet):
        """Check ETH balance on Base (for gas)."""
        from fundis.web3_utils import get_web3

        w3 = get_web3()
        raw = w3.eth.get_balance(first_wallet.address)
        eth_balance = Decimal(raw) / Decimal(10**18)
        print(f"✓ Base ETH balance: {eth_balance:.6f} ETH")
        return float(eth_balance)

    def test_arbitrum_usdc_balance(self, first_wallet):
        """Check USDC balance on Arbitrum."""
        from fundis.swidge import get_arbitrum_web3, get_arbitrum_usdc_balance

        w3 = get_arbitrum_web3()
        human, raw = get_arbitrum_usdc_balance(w3, first_wallet.address)
        print(f"✓ Arbitrum USDC balance: {human:.2f} USDC")
        return float(human)

    def test_arbitrum_eth_balance(self, first_wallet):
        """Check ETH balance on Arbitrum (for gas)."""
        from fundis.swidge import get_arbitrum_web3, get_arbitrum_eth_balance

        w3 = get_arbitrum_web3()
        eth_balance = get_arbitrum_eth_balance(w3, first_wallet.address)
        print(f"✓ Arbitrum ETH balance: {eth_balance:.6f} ETH")
        return float(eth_balance)

    def test_hyperliquid_balance(self, first_wallet):
        """Check USDC balance on Hyperliquid."""
        from fundis.hyperliquid import (
            get_hyperliquid_info,
            get_usdc_balance,
            get_margin_summary,
        )

        info = get_hyperliquid_info()
        balance = get_usdc_balance(info, first_wallet.address)
        margin = get_margin_summary(info, first_wallet.address)

        print(f"✓ Hyperliquid balance:")
        print(f"  Account value: ${margin['account_value']:.2f}")
        print(f"  Withdrawable: ${margin['withdrawable']:.2f}")
        print(f"  Margin used: ${margin['total_margin_used']:.2f}")
        return balance


# ============================================================================
# Logs Tests (No transactions)
# ============================================================================


class TestLogs:
    """Test logging functionality."""

    def test_log_creation_and_retrieval(self, memory_service, first_wallet):
        """Test creating and retrieving logs."""
        agent_name = "Test Agent"

        # Create a test log
        memory_service.log(
            "Integration test log entry",
            wallet_address=first_wallet.address,
            agent_name=agent_name,
        )

        # Retrieve logs
        logs = memory_service.get_logs(agent_name=agent_name, limit=1)
        assert len(logs) >= 1
        assert "Integration test" in logs[0].message
        print("✓ Log creation and retrieval works")

    def test_log_statistics(self, memory_service):
        """Test log statistics."""
        total = memory_service.get_log_count()
        agents = memory_service.get_distinct_agents()

        print(f"✓ Log statistics:")
        print(f"  Total logs: {total}")
        print(f"  Agents with logs: {len(agents)}")
        for agent in agents[:5]:  # Show first 5
            count = memory_service.get_log_count(agent_name=agent)
            print(f"    - {agent}: {count} logs")


# ============================================================================
# Hyperliquid Tests (May involve transactions)
# ============================================================================


class TestHyperliquid:
    """Test Hyperliquid functionality."""

    def test_hyperliquid_position_check(self, first_wallet):
        """Check current BTC position on Hyperliquid."""
        from fundis.hyperliquid import get_hyperliquid_info, get_position_info

        info = get_hyperliquid_info()
        pos = get_position_info(info, first_wallet.address, "BTC")

        if pos:
            print(f"✓ Current BTC position:")
            print(f"  Size: {pos.size} BTC")
            print(f"  Entry: ${pos.entry_price:.2f}")
            print(f"  PnL: ${pos.unrealized_pnl:.2f}")
            print(
                f"  Liq price: ${pos.liquidation_price if pos.liquidation_price else 'N/A'}"
            )
        else:
            print("✓ No open BTC position")

        return pos

    def test_hyperliquid_margin_check(self, first_wallet):
        """Test margin availability check."""
        from fundis.hyperliquid import get_hyperliquid_info, check_can_open_position

        info = get_hyperliquid_info()
        can_open, reason = check_can_open_position(
            info, first_wallet.address, TEST_ALLOCATION_USDC
        )

        print(f"✓ Margin check for ${TEST_ALLOCATION_USDC}:")
        print(f"  Can open: {can_open}")
        print(f"  Reason: {reason}")

        return can_open

    @pytest.mark.skipif(True, reason="Enable manually to test real trading")
    def test_hyperliquid_open_close_position(self, first_wallet):
        """
        REAL TRANSACTION TEST: Open and close a small BTC position.

        To enable: Change @pytest.mark.skipif(True, ...) to @pytest.mark.skipif(False, ...)
        """
        from fundis.hyperliquid import (
            get_hyperliquid_exchange,
            market_open_long_safe,
            market_close_long_safe,
        )

        print(
            f"\n⚠️  REAL TRANSACTION: Opening ${TEST_ALLOCATION_USDC} BTC long position..."
        )

        exchange = get_hyperliquid_exchange(first_wallet.private_key)

        # Open position
        open_result = market_open_long_safe(exchange, "BTC", TEST_ALLOCATION_USDC)
        print(f"  Open result: {open_result.status}")

        if open_result.success:
            print(
                f"  Filled: {open_result.filled_size} BTC @ ${open_result.avg_price:.2f}"
            )

            # Wait a moment
            time.sleep(2)

            # Close position
            print("  Closing position...")
            close_result = market_close_long_safe(exchange, "BTC")
            print(f"  Close result: {close_result.status}")

            if close_result.success:
                print(
                    f"  Closed: {close_result.filled_size} BTC @ ${close_result.avg_price:.2f}"
                )
        else:
            print(f"  Error: {open_result.error}")


# ============================================================================
# Bridge Tests (May involve transactions)
# ============================================================================


class TestBridge:
    """Test bridge functionality."""

    def test_bridge_balance_checks(self, first_wallet):
        """Check balances for bridge operations."""
        from fundis.swidge import (
            get_arbitrum_web3,
            get_arbitrum_usdc_balance,
            get_arbitrum_eth_balance,
            get_hyperliquid_withdrawable_balance,
        )

        w3 = get_arbitrum_web3()
        arb_usdc, _ = get_arbitrum_usdc_balance(w3, first_wallet.address)
        arb_eth = get_arbitrum_eth_balance(w3, first_wallet.address)
        hl_usdc = get_hyperliquid_withdrawable_balance(first_wallet.address)

        print(f"✓ Bridge-ready balances:")
        print(f"  Arbitrum USDC: {arb_usdc:.2f}")
        print(f"  Arbitrum ETH: {arb_eth:.6f} (for gas)")
        print(f"  Hyperliquid USDC: {hl_usdc:.2f}")

        return {
            "arb_usdc": float(arb_usdc),
            "arb_eth": float(arb_eth),
            "hl_usdc": hl_usdc,
        }

    @pytest.mark.skipif(True, reason="Enable manually to test real bridge deposit")
    def test_bridge_deposit(self, first_wallet):
        """
        REAL TRANSACTION TEST: Deposit 1 USDC from Arbitrum to Hyperliquid.

        To enable: Change @pytest.mark.skipif(True, ...) to @pytest.mark.skipif(False, ...)
        """
        from fundis.swidge import (
            get_arbitrum_web3,
            deposit_usdc_to_hyperliquid,
        )

        print(
            f"\n⚠️  REAL TRANSACTION: Depositing ${TEST_ALLOCATION_USDC} USDC to Hyperliquid..."
        )

        w3 = get_arbitrum_web3()
        result = deposit_usdc_to_hyperliquid(
            w3,
            first_wallet.address,
            first_wallet.private_key,
            TEST_ALLOCATION_USDC,
            print_fn=print,
        )

        if result.success:
            print(f"✓ Deposit successful: {result.amount_deposited} USDC")
            print(f"  TX: {result.tx_hash}")
        else:
            print(f"✗ Deposit failed: {result.error}")

        return result

    @pytest.mark.skipif(True, reason="Enable manually to test real bridge withdrawal")
    def test_bridge_withdraw(self, first_wallet):
        """
        REAL TRANSACTION TEST: Withdraw 2 USDC from Hyperliquid to Arbitrum.
        (Minimum withdrawal is 2 USDC due to $1 fee)

        To enable: Change @pytest.mark.skipif(True, ...) to @pytest.mark.skipif(False, ...)
        """
        from fundis.swidge import (
            withdraw_usdc_from_hyperliquid,
            HYPERLIQUID_MIN_WITHDRAWAL,
        )

        withdraw_amount = max(TEST_ALLOCATION_USDC + 1, HYPERLIQUID_MIN_WITHDRAWAL)
        print(
            f"\n⚠️  REAL TRANSACTION: Withdrawing ${withdraw_amount} USDC from Hyperliquid..."
        )

        result = withdraw_usdc_from_hyperliquid(
            first_wallet.address,
            first_wallet.private_key,
            withdraw_amount,
            print_fn=print,
        )

        if result.success:
            print(f"✓ Withdrawal initiated: {result.amount_withdrawn} USDC")
            print(f"  Fee: ${result.fee}")
            print(f"  Net: ${result.amount_withdrawn - result.fee}")
        else:
            print(f"✗ Withdrawal failed: {result.error}")

        return result


# ============================================================================
# Base Agent Tests (May involve transactions)
# ============================================================================


class TestBaseAgent:
    """Test Base network agent functionality."""

    def test_aerodrome_liquidity_check(self):
        """Check Aerodrome liquidity for USDC/WBTC pair."""
        from fundis.web3_utils import get_web3
        from fundis.aerodrome import try_aerodrome_swap_simulation
        from fundis.config import USDC_ADDRESS, WBTC_ADDRESS

        w3 = get_web3()

        # Try to simulate a small swap (1 USDC)
        amount_raw = 1_000_000  # 1 USDC (6 decimals)

        result = try_aerodrome_swap_simulation(
            w3,
            USDC_ADDRESS,
            WBTC_ADDRESS,
            amount_raw,
            "0x0000000000000000000000000000000000000001",
        )

        if result:
            output, routes = result
            print(f"✓ Aerodrome USDC→WBTC liquidity available")
            print(f"  1 USDC → ~{output / 10**8:.8f} WBTC")  # WBTC has 8 decimals
        else:
            print("✗ No Aerodrome liquidity for USDC→WBTC")

        return result is not None

    def test_allowance_check(self, first_wallet):
        """Check current USDC allowance for Aerodrome router."""
        from fundis.web3_utils import get_web3, to_checksum, ERC20_MINIMAL_ABI
        from fundis.config import USDC_ADDRESS, AERODROME_ROUTER_ADDRESS

        w3 = get_web3()
        usdc = w3.eth.contract(
            address=to_checksum(w3, USDC_ADDRESS),
            abi=ERC20_MINIMAL_ABI,
        )

        allowance = usdc.functions.allowance(
            to_checksum(w3, first_wallet.address),
            to_checksum(w3, AERODROME_ROUTER_ADDRESS),
        ).call()

        allowance_human = allowance / 10**6
        max_approval = 2**256 - 1

        if allowance == max_approval:
            print("✓ USDC allowance: MAX (unlimited)")
        elif allowance > 0:
            print(f"✓ USDC allowance: {allowance_human:.2f} USDC")
        else:
            print("✓ USDC allowance: 0 (needs approval)")

        return allowance

    @pytest.mark.skipif(True, reason="Enable manually to test real swap")
    def test_base_swap_usdc_to_wbtc(self, first_wallet, memory_service):
        """
        REAL TRANSACTION TEST: Swap 1 USDC to WBTC on Base.

        To enable: Change @pytest.mark.skipif(True, ...) to @pytest.mark.skipif(False, ...)
        """
        from fundis.web3_utils import get_web3
        from fundis.agents.base import AgentContext

        print(
            f"\n⚠️  REAL TRANSACTION: Swapping ${TEST_ALLOCATION_USDC} USDC to WBTC..."
        )

        # This would need to be implemented as a direct call to _perform_swap
        # For now, you can test via the CLI: fundis agent
        print("  Note: Use `fundis agent` to test actual swaps")
        print("  Select 'SentiChain BTC Agent on Base' with 1 USDC allocation")


# ============================================================================
# Custom Allocation Tests
# ============================================================================


class TestCustomAllocation:
    """Test custom allocation functionality."""

    def test_allocation_stored_correctly(self, memory_service, first_wallet):
        """Test that allocation is stored in position record."""
        from fundis.memory import Position
        from datetime import datetime, timezone

        test_agent = "Test Allocation Agent"
        test_allocation = 42.0

        # Create a position with custom allocation
        pos = Position(
            wallet_address=first_wallet.address,
            agent_name=test_agent,
            ticker="TEST",
            base_token="USDC",
            quote_token="TEST",
            allocated_amount=test_allocation,
            allocated_amount_raw=int(test_allocation * 1_000_000),
            current_position="USDC",
            last_updated_at=datetime.now(timezone.utc).isoformat(),
        )
        memory_service.upsert_position(pos)

        # Retrieve and verify
        retrieved = memory_service.get_position(first_wallet.address, test_agent)
        assert retrieved is not None
        assert retrieved.allocated_amount == test_allocation
        print(f"✓ Allocation stored correctly: {retrieved.allocated_amount} USDC")

        # Cleanup - we don't have a delete method, but the test position won't affect anything


# ============================================================================
# Summary Test
# ============================================================================


class TestSummary:
    """Print a summary of all checks."""

    def test_print_summary(self, first_wallet):
        """Print a summary of wallet status across all networks."""
        from fundis.web3_utils import get_web3, get_erc20_balance
        from fundis.config import USDC_ADDRESS
        from fundis.swidge import (
            get_arbitrum_web3,
            get_arbitrum_usdc_balance,
            get_arbitrum_eth_balance,
            get_hyperliquid_withdrawable_balance,
        )
        from fundis.hyperliquid import get_hyperliquid_info, get_all_open_positions

        print("\n" + "=" * 60)
        print("WALLET SUMMARY")
        print("=" * 60)
        print(f"Address: {first_wallet.address}")
        print()

        # Base
        try:
            w3_base = get_web3()
            base_usdc, _, _ = get_erc20_balance(
                w3_base, USDC_ADDRESS, first_wallet.address
            )
            base_eth = Decimal(w3_base.eth.get_balance(first_wallet.address)) / Decimal(
                10**18
            )
            print(f"BASE NETWORK:")
            print(f"  USDC: {base_usdc:.2f}")
            print(f"  ETH:  {base_eth:.6f}")
        except Exception as e:
            print(f"BASE NETWORK: Error - {e}")

        # Arbitrum
        try:
            w3_arb = get_arbitrum_web3()
            arb_usdc, _ = get_arbitrum_usdc_balance(w3_arb, first_wallet.address)
            arb_eth = get_arbitrum_eth_balance(w3_arb, first_wallet.address)
            print(f"\nARBITRUM:")
            print(f"  USDC: {arb_usdc:.2f}")
            print(f"  ETH:  {arb_eth:.6f}")
        except Exception as e:
            print(f"\nARBITRUM: Error - {e}")

        # Hyperliquid
        try:
            hl_usdc = get_hyperliquid_withdrawable_balance(first_wallet.address)
            info = get_hyperliquid_info()
            positions = get_all_open_positions(info, first_wallet.address)
            print(f"\nHYPERLIQUID:")
            print(f"  Available USDC: {hl_usdc:.2f}")
            print(f"  Open positions: {len(positions)}")
            for pos in positions:
                coin = pos.get("coin", "?")
                size = float(pos.get("szi", 0))
                pnl = float(pos.get("unrealizedPnl", 0))
                print(f"    - {coin}: {size:+.4f} (PnL: ${pnl:+.2f})")
        except Exception as e:
            print(f"\nHYPERLIQUID: Error - {e}")

        print("\n" + "=" * 60)
        print(f"Ready to test with ${TEST_ALLOCATION_USDC} USDC transactions")
        print("=" * 60)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])

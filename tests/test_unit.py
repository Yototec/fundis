"""
Unit tests for Fundis - No real transactions, just logic validation.

Run with: pytest tests/test_unit.py -v
"""

import pytest
from decimal import Decimal
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone


class TestAgentContext:
    """Test AgentContext with custom allocation."""

    def test_default_allocation(self):
        """AgentContext should have default allocation of 10 USDC."""
        from fundis.agents.base import AgentContext, DEFAULT_ALLOCATION_USDC

        assert DEFAULT_ALLOCATION_USDC == 10.0

        # Create context with defaults
        ctx = AgentContext(
            wallet_address="0x1234",
            private_key="0xabc",
            memory=MagicMock(),
            print=print,
        )
        assert ctx.allocation_usdc == 10.0

    def test_custom_allocation(self):
        """AgentContext should accept custom allocation."""
        from fundis.agents.base import AgentContext

        ctx = AgentContext(
            wallet_address="0x1234",
            private_key="0xabc",
            memory=MagicMock(),
            print=print,
            allocation_usdc=50.0,
        )
        assert ctx.allocation_usdc == 50.0


class TestMemoryService:
    """Test MemoryService log functionality."""

    def test_log_entry_creation(self):
        """LogEntry dataclass should store all fields."""
        from fundis.memory import LogEntry

        log = LogEntry(
            id=1,
            created_at="2024-01-01T00:00:00Z",
            wallet_address="0x1234",
            agent_name="Test Agent",
            level="INFO",
            message="Test message",
        )
        assert log.id == 1
        assert log.level == "INFO"
        assert log.message == "Test message"

    def test_memory_service_logs(self, tmp_path):
        """MemoryService should store and retrieve logs."""
        from fundis.memory import MemoryService

        db_path = tmp_path / "test_memory.db"
        mem = MemoryService(db_path=db_path)

        # Create logs
        mem.log("Test message 1", wallet_address="0x1234", agent_name="Agent1")
        mem.log("Test message 2", wallet_address="0x1234", agent_name="Agent1")
        mem.log("Test message 3", wallet_address="0x5678", agent_name="Agent2")

        # Test get_logs
        all_logs = mem.get_logs()
        assert len(all_logs) == 3

        # Test filter by agent
        agent1_logs = mem.get_logs(agent_name="Agent1")
        assert len(agent1_logs) == 2

        # Test filter by wallet
        wallet_logs = mem.get_logs(wallet_address="0x5678")
        assert len(wallet_logs) == 1

        # Test get_log_count
        assert mem.get_log_count() == 3
        assert mem.get_log_count(agent_name="Agent1") == 2

        # Test get_distinct_agents
        agents = mem.get_distinct_agents()
        assert set(agents) == {"Agent1", "Agent2"}

        # Test clear_logs
        deleted = mem.clear_logs(agent_name="Agent1")
        assert deleted == 2
        assert mem.get_log_count() == 1

        mem.close()


class TestHyperliquidModule:
    """Test Hyperliquid module structures."""

    def test_order_result_dataclass(self):
        """OrderResult should store order execution results."""
        from fundis.hyperliquid import OrderResult

        result = OrderResult(
            success=True,
            filled_size=0.001,
            avg_price=95000.0,
            status="filled",
        )
        assert result.success is True
        assert result.filled_size == 0.001
        assert result.status == "filled"
        assert result.error is None

    def test_order_result_with_error(self):
        """OrderResult should store errors."""
        from fundis.hyperliquid import OrderResult

        result = OrderResult(
            success=False,
            filled_size=0,
            avg_price=0,
            status="margin_check_failed",
            error="Insufficient margin",
        )
        assert result.success is False
        assert result.error == "Insufficient margin"

    def test_position_info_dataclass(self):
        """PositionInfo should store position details."""
        from fundis.hyperliquid import PositionInfo

        pos = PositionInfo(
            coin="BTC",
            size=0.001,
            entry_price=95000.0,
            unrealized_pnl=10.5,
            liquidation_price=90000.0,
            margin_used=100.0,
            leverage=1.0,
        )
        assert pos.coin == "BTC"
        assert pos.size == 0.001
        assert pos.liquidation_price == 90000.0

    def test_parse_order_result_filled(self):
        """parse_order_result should handle filled orders."""
        from fundis.hyperliquid import parse_order_result

        raw_result = {
            "status": "ok",
            "response": {
                "data": {
                    "statuses": [{"filled": {"totalSz": "0.001", "avgPx": "95000"}}]
                }
            },
        }
        result = parse_order_result(raw_result)
        assert result.success is True
        assert result.status == "filled"
        assert result.filled_size == 0.001
        assert result.avg_price == 95000.0

    def test_parse_order_result_error(self):
        """parse_order_result should handle errors."""
        from fundis.hyperliquid import parse_order_result

        raw_result = {
            "status": "ok",
            "response": {"data": {"statuses": [{"error": "Insufficient margin"}]}},
        }
        result = parse_order_result(raw_result)
        assert result.success is False
        assert result.status == "error"
        assert result.error == "Insufficient margin"


class TestSwidgeModule:
    """Test Swidge module structures."""

    def test_deposit_result_dataclass(self):
        """DepositResult should store deposit results."""
        from fundis.swidge import DepositResult

        result = DepositResult(
            success=True,
            tx_hash="0xabc123",
            amount_deposited=10.0,
        )
        assert result.success is True
        assert result.tx_hash == "0xabc123"
        assert result.amount_deposited == 10.0

    def test_withdrawal_result_dataclass(self):
        """WithdrawalResult should store withdrawal results."""
        from fundis.swidge import WithdrawalResult

        result = WithdrawalResult(
            success=True,
            amount_withdrawn=10.0,
            fee=1.0,
        )
        assert result.success is True
        assert result.amount_withdrawn == 10.0
        assert result.fee == 1.0

    def test_withdrawal_constants(self):
        """Withdrawal constants should be correct."""
        from fundis.swidge import HYPERLIQUID_WITHDRAWAL_FEE, HYPERLIQUID_MIN_WITHDRAWAL

        assert HYPERLIQUID_WITHDRAWAL_FEE == 1.0
        assert HYPERLIQUID_MIN_WITHDRAWAL == 2.0


class TestConfigModule:
    """Test config module."""

    def test_arbitrum_config(self):
        """Arbitrum config should be present."""
        from fundis.config import (
            ARBITRUM_CHAIN_ID,
            ARBITRUM_RPC_URL,
            ARBITRUM_USDC_ADDRESS,
            HYPERLIQUID_BRIDGE_ADDRESS,
        )

        assert ARBITRUM_CHAIN_ID == 42161
        assert "arbitrum" in ARBITRUM_RPC_URL.lower()
        assert ARBITRUM_USDC_ADDRESS.startswith("0x")
        assert HYPERLIQUID_BRIDGE_ADDRESS.startswith("0x")


class TestAllocationLogic:
    """Test allocation logic (min of balance and allocation)."""

    def test_min_allocation_logic(self):
        """Allocation should use min(balance, allocation)."""

        # Simulate the logic used in agents
        def calculate_trade_amount(balance: float, allocation: float) -> float:
            return min(balance, allocation)

        # User sets 100, has 7 -> trade 7
        assert calculate_trade_amount(7, 100) == 7

        # User sets 100, has 80 -> trade 80
        assert calculate_trade_amount(80, 100) == 80

        # User sets 100, has 150 -> trade 100
        assert calculate_trade_amount(150, 100) == 100

        # User sets 50, has 50 -> trade 50
        assert calculate_trade_amount(50, 50) == 50


class TestMaxApproval:
    """Test max approval constant."""

    def test_max_approval_value(self):
        """Max approval should be 2^256 - 1."""
        MAX_APPROVAL = 2**256 - 1
        assert (
            MAX_APPROVAL
            == 115792089237316195423570985008687907853269984665640564039457584007913129639935
        )


class TestAgentRegistry:
    """Test agent registry."""

    def test_list_agent_names(self):
        """Should list available agents."""
        from fundis.agents.registry import list_agent_names

        names = list_agent_names()
        assert "SentiChain BTC Agent on Hyperliquid" in names
        assert "SentiChain ETH Agent on Hyperliquid" in names
        assert len(names) == 2

    def test_get_agent(self):
        """Should get agent module by name."""
        from fundis.agents.registry import get_agent

        agent = get_agent("SentiChain BTC Agent on Hyperliquid")
        assert hasattr(agent, "run_update")
        assert hasattr(agent, "run_unwind")
        assert agent.AGENT_NAME == "SentiChain BTC Agent on Hyperliquid"


class TestTradingSignalParsing:
    """Test trading signal parsing from SentiChain API."""

    def test_parse_trading_signal(self):
        """Should parse trading signal JSON correctly."""
        from fundis.agents.sentichain_btc_hyperliquid import _parse_trading_signal

        payload = {
            "reasoning": '''```json
{
    "ticker": "BTC",
    "timestamp": "2025-12-01T13:15:00Z",
    "signal": {
        "direction": "LONG",
        "confidence": 0.8,
        "strength": "STRONG"
    },
    "position": {
        "sizing": "HALF",
        "max_allocation_pct": 10,
        "leverage_recommended": "NONE"
    },
    "timing": {
        "urgency": "IMMEDIATE",
        "suggested_entry": "Enter on breakout",
        "timeframe": "1-3 days"
    },
    "risk_management": {
        "stop_loss_condition": "Close below 80000",
        "take_profit_condition": "Scale at 100000",
        "invalidation": "Daily close below 80000"
    },
    "metadata": {
        "data_quality": "HIGH",
        "conviction_score": 8,
        "risk_rating": "MEDIUM"
    }
}
```'''
        }

        signal = _parse_trading_signal(payload)
        assert signal is not None
        assert signal.ticker == "BTC"
        assert signal.direction == "LONG"
        assert signal.confidence == 0.8
        assert signal.strength == "STRONG"
        assert signal.conviction_score == 8

    def test_parse_trading_signal_short(self):
        """Should parse SHORT signal correctly."""
        from fundis.agents.sentichain_btc_hyperliquid import _parse_trading_signal

        payload = {
            "reasoning": '''```json
{
    "ticker": "BTC",
    "timestamp": "2025-12-01T13:15:00Z",
    "signal": {
        "direction": "SHORT",
        "confidence": 0.6,
        "strength": "MODERATE"
    },
    "position": {"sizing": "QUARTER", "max_allocation_pct": 5},
    "timing": {"urgency": "IMMEDIATE"},
    "risk_management": {},
    "metadata": {"conviction_score": 6, "risk_rating": "HIGH"}
}
```'''
        }

        signal = _parse_trading_signal(payload)
        assert signal is not None
        assert signal.direction == "SHORT"
        assert signal.confidence == 0.6

    def test_parse_trading_signal_empty(self):
        """Should return None for empty payload."""
        from fundis.agents.sentichain_btc_hyperliquid import _parse_trading_signal

        assert _parse_trading_signal({}) is None
        assert _parse_trading_signal({"reasoning": ""}) is None
        assert _parse_trading_signal({"reasoning": "invalid"}) is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

#!/usr/bin/env python3
"""
Fundis Test Runner

A convenient script to run different categories of tests.

Usage:
    python tests/run_tests.py [category]

Categories:
    unit        - Run unit tests only (no network/transactions)
    connect     - Test network connections only
    balance     - Check balances on all networks
    logs        - Test logging functionality
    summary     - Print wallet summary
    signals     - Test SentiChain trading signal API
    all-safe    - Run all tests that don't involve transactions
    
For real transaction tests, use pytest directly:
    pytest tests/test_integration.py::TestHyperliquid::test_hyperliquid_open_close_position -v -s
"""

import sys
import subprocess


def run_pytest(args):
    """Run pytest with given arguments."""
    cmd = ["python", "-m", "pytest"] + args
    print(f"Running: {' '.join(cmd)}\n")
    return subprocess.call(cmd)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print("\nAvailable test categories:")
        print("  unit       - Unit tests (no network)")
        print("  connect    - Connection tests")
        print("  balance    - Balance checks")
        print("  logs       - Logging tests")
        print("  signals    - Trading signal API tests")
        print("  summary    - Wallet summary")
        print("  hyperliquid - Hyperliquid tests")
        print("  bridge     - Bridge tests")
        print("  all-safe   - All safe tests")
        return 0

    category = sys.argv[1].lower()

    if category == "unit":
        return run_pytest(["tests/test_unit.py", "-v"])

    elif category == "connect":
        return run_pytest(["tests/test_integration.py::TestConnections", "-v", "-s"])

    elif category == "balance":
        return run_pytest(["tests/test_integration.py::TestBalances", "-v", "-s"])

    elif category == "logs":
        return run_pytest(["tests/test_integration.py::TestLogs", "-v", "-s"])

    elif category == "signals":
        return run_pytest(["tests/test_integration.py::TestTradingSignals", "-v", "-s"])

    elif category == "summary":
        return run_pytest(["tests/test_integration.py::TestSummary", "-v", "-s"])

    elif category == "hyperliquid":
        return run_pytest(["tests/test_integration.py::TestHyperliquid", "-v", "-s"])

    elif category == "bridge":
        return run_pytest(["tests/test_integration.py::TestBridge", "-v", "-s"])

    elif category == "all-safe":
        # Run all tests except those marked as skip
        return run_pytest(
            [
                "tests/test_unit.py",
                "tests/test_integration.py::TestConnections",
                "tests/test_integration.py::TestBalances",
                "tests/test_integration.py::TestLogs",
                "tests/test_integration.py::TestTradingSignals",
                "tests/test_integration.py::TestHyperliquid::test_hyperliquid_position_check",
                "tests/test_integration.py::TestHyperliquid::test_hyperliquid_margin_check",
                "tests/test_integration.py::TestBridge::test_bridge_balance_checks",
                "tests/test_integration.py::TestCustomAllocation",
                "tests/test_integration.py::TestSummary",
                "-v",
                "-s",
            ]
        )

    elif category == "all":
        return run_pytest(["tests/", "-v", "-s"])

    else:
        print(f"Unknown category: {category}")
        print("Run without arguments to see available categories.")
        return 1


if __name__ == "__main__":
    sys.exit(main())

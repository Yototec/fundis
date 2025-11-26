"""
Swidge - Swap and Bridge utilities.

This module provides helpers for:
- Bridging USDC from Arbitrum to Hyperliquid
- (Future) Cross-chain swaps and bridges
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Tuple

from web3 import Web3
from web3.exceptions import ContractLogicError

from .config import (
    ARBITRUM_CHAIN_ID,
    ARBITRUM_RPC_URL,
    ARBITRUM_USDC_ADDRESS,
    HYPERLIQUID_BRIDGE_ADDRESS,
)
from .hyperliquid import (
    get_hyperliquid_exchange,
    get_hyperliquid_info,
    get_usdc_balance as get_hyperliquid_usdc_balance,
)

# Hyperliquid Bridge ABI (minimal - just the deposit function)
# The bridge accepts USDC deposits and credits them to your Hyperliquid account
HYPERLIQUID_BRIDGE_ABI = [
    {
        "inputs": [{"internalType": "uint64", "name": "amount", "type": "uint64"}],
        "name": "deposit",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]

# ERC20 minimal ABI for USDC
ERC20_ABI = [
    {
        "inputs": [{"name": "account", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "spender", "type": "address"},
            {"name": "amount", "type": "uint256"},
        ],
        "name": "approve",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "owner", "type": "address"},
            {"name": "spender", "type": "address"},
        ],
        "name": "allowance",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "symbol",
        "outputs": [{"name": "", "type": "string"}],
        "stateMutability": "view",
        "type": "function",
    },
]


@dataclass
class DepositResult:
    """Result of a deposit operation."""

    success: bool
    tx_hash: str | None
    amount_deposited: float
    error: str | None = None


def get_arbitrum_web3() -> Web3:
    """Get a Web3 instance connected to Arbitrum."""
    return Web3(Web3.HTTPProvider(ARBITRUM_RPC_URL))


def get_arbitrum_usdc_balance(w3: Web3, wallet_address: str) -> Tuple[Decimal, int]:
    """
    Get USDC balance on Arbitrum.

    Returns:
        (human_readable_balance, raw_balance)
    """
    usdc = w3.eth.contract(
        address=Web3.to_checksum_address(ARBITRUM_USDC_ADDRESS),
        abi=ERC20_ABI,
    )

    raw_balance = usdc.functions.balanceOf(
        Web3.to_checksum_address(wallet_address)
    ).call()

    decimals = usdc.functions.decimals().call()
    human_balance = Decimal(raw_balance) / Decimal(10**decimals)

    return human_balance, raw_balance


def get_arbitrum_eth_balance(w3: Web3, wallet_address: str) -> Decimal:
    """Get ETH balance on Arbitrum (for gas)."""
    raw_balance = w3.eth.get_balance(Web3.to_checksum_address(wallet_address))
    return Decimal(raw_balance) / Decimal(10**18)


def estimate_deposit_gas(w3: Web3) -> int:
    """Estimate gas needed for approval + deposit."""
    # Approval typically costs ~50k gas, deposit ~100k gas
    # Adding buffer for safety
    return 200_000


def deposit_usdc_to_hyperliquid(
    w3: Web3,
    wallet_address: str,
    private_key: str,
    amount_usdc: float,
    print_fn=print,
) -> DepositResult:
    """
    Deposit USDC from Arbitrum to Hyperliquid.

    This function:
    1. Checks USDC and ETH balances
    2. Approves USDC for the Hyperliquid bridge (if needed)
    3. Calls the bridge deposit function

    Args:
        w3: Web3 instance connected to Arbitrum
        wallet_address: The wallet address
        private_key: Private key for signing transactions
        amount_usdc: Amount of USDC to deposit (human readable, e.g., 10.0)
        print_fn: Function to print status messages

    Returns:
        DepositResult with success status and transaction hash
    """
    wallet = Web3.to_checksum_address(wallet_address)
    bridge_address = Web3.to_checksum_address(HYPERLIQUID_BRIDGE_ADDRESS)
    usdc_address = Web3.to_checksum_address(ARBITRUM_USDC_ADDRESS)

    # Minimum deposit is 5 USDC
    if amount_usdc < 5:
        return DepositResult(
            success=False,
            tx_hash=None,
            amount_deposited=0,
            error="Minimum deposit is 5 USDC",
        )

    # Get contracts
    usdc = w3.eth.contract(address=usdc_address, abi=ERC20_ABI)
    bridge = w3.eth.contract(address=bridge_address, abi=HYPERLIQUID_BRIDGE_ABI)

    # Check balances
    print_fn("Checking balances on Arbitrum...")

    try:
        usdc_balance, usdc_raw = get_arbitrum_usdc_balance(w3, wallet_address)
        eth_balance = get_arbitrum_eth_balance(w3, wallet_address)
    except Exception as exc:
        return DepositResult(
            success=False,
            tx_hash=None,
            amount_deposited=0,
            error=f"Error checking balances: {exc!r}",
        )

    print_fn(f"  USDC balance: {usdc_balance:.2f} USDC")
    print_fn(f"  ETH balance: {eth_balance:.6f} ETH (for gas)")

    # USDC has 6 decimals
    amount_raw = int(amount_usdc * 1_000_000)

    if usdc_raw < amount_raw:
        return DepositResult(
            success=False,
            tx_hash=None,
            amount_deposited=0,
            error=f"Insufficient USDC: have {usdc_balance:.2f}, need {amount_usdc:.2f}",
        )

    # Estimate gas cost (rough)
    gas_price = w3.eth.gas_price
    estimated_gas = estimate_deposit_gas(w3)
    estimated_cost_wei = gas_price * estimated_gas
    estimated_cost_eth = Decimal(estimated_cost_wei) / Decimal(10**18)

    if eth_balance < estimated_cost_eth * Decimal("1.5"):  # 50% buffer
        return DepositResult(
            success=False,
            tx_hash=None,
            amount_deposited=0,
            error=f"Insufficient ETH for gas: have {eth_balance:.6f}, need ~{estimated_cost_eth:.6f}",
        )

    print_fn(f"Estimated gas cost: ~{estimated_cost_eth:.6f} ETH")

    # Check allowance and approve if needed (always check, as user may have revoked)
    # Use max approval (2**256 - 1) to avoid repeated approvals
    MAX_APPROVAL = 2**256 - 1

    try:
        allowance = usdc.functions.allowance(wallet, bridge_address).call()
        print_fn(f"Current USDC allowance for bridge: {allowance / 1_000_000:.2f}")
    except Exception as exc:
        return DepositResult(
            success=False,
            tx_hash=None,
            amount_deposited=0,
            error=f"Error checking allowance: {exc!r}",
        )

    nonce = w3.eth.get_transaction_count(wallet, "pending")

    if allowance < amount_raw:
        print_fn("Approving max USDC for Hyperliquid bridge (one-time approval)...")

        try:
            # Approve for max amount to avoid repeated approvals
            approve_tx = usdc.functions.approve(
                bridge_address, MAX_APPROVAL
            ).build_transaction(
                {
                    "from": wallet,
                    "nonce": nonce,
                    "gas": 100_000,
                    "gasPrice": gas_price,
                    "chainId": ARBITRUM_CHAIN_ID,
                }
            )

            signed_approve = w3.eth.account.sign_transaction(approve_tx, private_key)
            approve_hash = w3.eth.send_raw_transaction(signed_approve.raw_transaction)

            print_fn(f"Approval tx sent: {approve_hash.hex()}")
            print_fn("Waiting for confirmation...")

            approve_receipt = w3.eth.wait_for_transaction_receipt(
                approve_hash, timeout=120
            )

            if approve_receipt.status != 1:
                return DepositResult(
                    success=False,
                    tx_hash=approve_hash.hex(),
                    amount_deposited=0,
                    error="Approval transaction failed",
                )

            print_fn(f"Max approval confirmed in block {approve_receipt.blockNumber}.")
            nonce += 1

        except Exception as exc:
            return DepositResult(
                success=False,
                tx_hash=None,
                amount_deposited=0,
                error=f"Approval failed: {exc!r}",
            )

    # Execute deposit
    print_fn(f"Depositing {amount_usdc} USDC to Hyperliquid...")

    try:
        # The bridge deposit function takes amount as uint64 (in USDC's smallest unit)
        deposit_tx = bridge.functions.deposit(amount_raw).build_transaction(
            {
                "from": wallet,
                "nonce": nonce,
                "gas": 150_000,
                "gasPrice": gas_price,
                "chainId": ARBITRUM_CHAIN_ID,
            }
        )

        signed_deposit = w3.eth.account.sign_transaction(deposit_tx, private_key)
        deposit_hash = w3.eth.send_raw_transaction(signed_deposit.raw_transaction)

        print_fn(f"Deposit tx sent: {deposit_hash.hex()}")
        print_fn("Waiting for confirmation...")

        deposit_receipt = w3.eth.wait_for_transaction_receipt(deposit_hash, timeout=120)

        if deposit_receipt.status != 1:
            return DepositResult(
                success=False,
                tx_hash=deposit_hash.hex(),
                amount_deposited=0,
                error="Deposit transaction reverted",
            )

        tx_hash_hex = deposit_hash.hex()
        arbiscan_url = f"https://arbiscan.io/tx/{tx_hash_hex}"

        print_fn(f"Deposit confirmed in block {deposit_receipt.blockNumber}.")
        print_fn(f"View on Arbiscan: {arbiscan_url}")
        print_fn("")
        print_fn("Note: Your USDC should appear on Hyperliquid within a few minutes.")

        return DepositResult(
            success=True,
            tx_hash=tx_hash_hex,
            amount_deposited=amount_usdc,
        )

    except ContractLogicError as exc:
        return DepositResult(
            success=False,
            tx_hash=None,
            amount_deposited=0,
            error=f"Contract error: {exc!r}",
        )
    except Exception as exc:
        return DepositResult(
            success=False,
            tx_hash=None,
            amount_deposited=0,
            error=f"Deposit failed: {exc!r}",
        )


def check_hyperliquid_balance_after_deposit(
    wallet_address: str,
    timeout_seconds: int = 300,
    print_fn=print,
) -> float | None:
    """
    Check Hyperliquid balance after deposit.

    Hyperliquid deposits typically take 1-5 minutes to appear.

    Args:
        wallet_address: The wallet address
        timeout_seconds: How long to wait (default 5 minutes)
        print_fn: Function to print status messages

    Returns:
        Current USDC balance on Hyperliquid, or None if error
    """
    print_fn("Checking balance on Hyperliquid...")

    try:
        info = get_hyperliquid_info()
        balance = get_hyperliquid_usdc_balance(info, wallet_address)
        print_fn(f"Current Hyperliquid balance: {balance:.2f} USDC")
        return balance
    except Exception as exc:
        print_fn(f"Error checking Hyperliquid balance: {exc!r}")
        return None


# --------------------------------------------------------------------------- #
# Hyperliquid -> Arbitrum Withdrawal
# --------------------------------------------------------------------------- #

# Hyperliquid withdrawal fee (in USDC)
HYPERLIQUID_WITHDRAWAL_FEE = 1.0

# Minimum withdrawal amount (must be > fee)
HYPERLIQUID_MIN_WITHDRAWAL = 2.0


@dataclass
class WithdrawalResult:
    """Result of a withdrawal operation."""

    success: bool
    amount_withdrawn: float
    fee: float
    error: str | None = None


def get_hyperliquid_withdrawable_balance(wallet_address: str) -> float:
    """
    Get the withdrawable USDC balance on Hyperliquid.

    This is the amount available to withdraw (not locked in positions).
    """
    info = get_hyperliquid_info()
    return get_hyperliquid_usdc_balance(info, wallet_address)


def withdraw_usdc_from_hyperliquid(
    wallet_address: str,
    private_key: str,
    amount_usdc: float,
    destination_address: str | None = None,
    print_fn=print,
) -> WithdrawalResult:
    """
    Withdraw USDC from Hyperliquid to Arbitrum.

    This function:
    1. Checks withdrawable balance on Hyperliquid
    2. Validates amount (must be > $1 fee)
    3. Initiates withdrawal via Hyperliquid API

    Args:
        wallet_address: The wallet address on Hyperliquid
        private_key: Private key for signing the withdrawal
        amount_usdc: Amount of USDC to withdraw (before fee)
        destination_address: Arbitrum address to receive funds (defaults to same address)
        print_fn: Function to print status messages

    Returns:
        WithdrawalResult with success status

    Note:
        - Hyperliquid charges a $1 USDC withdrawal fee
        - Withdrawals typically complete in 3-5 minutes
        - Funds are sent to the same address on Arbitrum by default
    """
    # Default destination to same address
    if destination_address is None:
        destination_address = wallet_address

    # Validate amount
    if amount_usdc < HYPERLIQUID_MIN_WITHDRAWAL:
        return WithdrawalResult(
            success=False,
            amount_withdrawn=0,
            fee=HYPERLIQUID_WITHDRAWAL_FEE,
            error=f"Minimum withdrawal is {HYPERLIQUID_MIN_WITHDRAWAL} USDC (fee is ${HYPERLIQUID_WITHDRAWAL_FEE})",
        )

    # Check balance
    print_fn("Checking withdrawable balance on Hyperliquid...")

    try:
        info = get_hyperliquid_info()
        withdrawable = get_hyperliquid_usdc_balance(info, wallet_address)
        print_fn(f"  Withdrawable balance: {withdrawable:.2f} USDC")
    except Exception as exc:
        return WithdrawalResult(
            success=False,
            amount_withdrawn=0,
            fee=HYPERLIQUID_WITHDRAWAL_FEE,
            error=f"Error checking Hyperliquid balance: {exc!r}",
        )

    if withdrawable < amount_usdc:
        return WithdrawalResult(
            success=False,
            amount_withdrawn=0,
            fee=HYPERLIQUID_WITHDRAWAL_FEE,
            error=f"Insufficient withdrawable balance: have {withdrawable:.2f}, need {amount_usdc:.2f}",
        )

    # Calculate net amount after fee
    net_amount = amount_usdc - HYPERLIQUID_WITHDRAWAL_FEE

    print_fn(f"Initiating withdrawal of {amount_usdc:.2f} USDC...")
    print_fn(f"  Fee: ${HYPERLIQUID_WITHDRAWAL_FEE:.2f}")
    print_fn(f"  You will receive: ${net_amount:.2f} USDC on Arbitrum")
    print_fn(f"  Destination: {destination_address}")

    try:
        exchange = get_hyperliquid_exchange(private_key)

        # The SDK's withdraw method sends USDC to the specified address on Arbitrum
        # Amount is in USD (not raw units)
        result = exchange.withdraw(amount_usdc, destination_address)

        status = result.get("status", "")
        response = result.get("response", {})

        if status == "ok":
            print_fn("")
            print_fn("Withdrawal initiated successfully.")
            print_fn(f"Amount: {amount_usdc:.2f} USDC")
            print_fn(f"Net (after fee): {net_amount:.2f} USDC")
            print_fn(f"Destination: {destination_address}")
            print_fn("")
            print_fn("Note: Withdrawals typically complete in 3-5 minutes.")
            print_fn("Check your Arbitrum wallet for the incoming USDC.")

            return WithdrawalResult(
                success=True,
                amount_withdrawn=amount_usdc,
                fee=HYPERLIQUID_WITHDRAWAL_FEE,
            )
        else:
            error_msg = (
                response.get("error", str(response))
                if isinstance(response, dict)
                else str(response)
            )
            return WithdrawalResult(
                success=False,
                amount_withdrawn=0,
                fee=HYPERLIQUID_WITHDRAWAL_FEE,
                error=f"Withdrawal failed: {error_msg}",
            )

    except Exception as exc:
        return WithdrawalResult(
            success=False,
            amount_withdrawn=0,
            fee=HYPERLIQUID_WITHDRAWAL_FEE,
            error=f"Withdrawal error: {exc!r}",
        )

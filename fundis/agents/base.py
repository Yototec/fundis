from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from web3 import Web3

from ..memory import MemoryService


PrintFn = Callable[[str], None]


@dataclass
class AgentContext:
    """
    Context passed into every agent.

    Agent authors can rely on:
    - ctx.web3: a Web3 instance
    - ctx.wallet_address: EVM address of the active wallet
    - ctx.private_key: private key for signing transactions
    - ctx.memory: MemoryService instance for logging and positions
    - ctx.print: function to print messages back to the CLI
    - ctx.chain_id: EVM chain id (Base mainnet by default)
    """

    web3: Web3
    wallet_address: str
    private_key: str
    memory: MemoryService
    print: PrintFn
    chain_id: int



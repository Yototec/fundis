from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from ..memory import MemoryService


PrintFn = Callable[[str], None]


# Default allocation amount in USDC
DEFAULT_ALLOCATION_USDC: float = 10.0


@dataclass
class AgentContext:
    """
    Context passed into every agent.

    Agent authors can rely on:
    - ctx.wallet_address: EVM address of the active wallet
    - ctx.private_key: private key for signing transactions
    - ctx.memory: MemoryService instance for logging and positions
    - ctx.print: function to print messages back to the CLI
    - ctx.allocation_usdc: allocation amount in USDC (default 10.0)
    """

    wallet_address: str
    private_key: str
    memory: MemoryService
    print: PrintFn
    allocation_usdc: float = DEFAULT_ALLOCATION_USDC

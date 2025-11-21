from __future__ import annotations

from ..config import WETH_ADDRESS
from .base import AgentContext
from .sentichain_common import run_unwind_generic, run_update_generic


AGENT_NAME = "SentiChain ETH Agent on Base"
TICKER = "ETH"
QUOTE_TOKEN = WETH_ADDRESS
QUOTE_SYMBOL = "WETH"


def run_update(ctx: AgentContext) -> None:
    run_update_generic(
        ctx,
        agent_name=AGENT_NAME,
        ticker=TICKER,
        quote_token=QUOTE_TOKEN,
        quote_symbol=QUOTE_SYMBOL,
    )


def run_unwind(ctx: AgentContext) -> None:
    run_unwind_generic(
        ctx,
        agent_name=AGENT_NAME,
        ticker=TICKER,
        quote_token=QUOTE_TOKEN,
        quote_symbol=QUOTE_SYMBOL,
    )

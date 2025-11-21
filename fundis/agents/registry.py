from __future__ import annotations

from typing import Dict, List, Protocol, runtime_checkable

from .base import AgentContext
from . import sentichain_eth, sentichain_btc


@runtime_checkable
class AgentModule(Protocol):
    AGENT_NAME: str

    def run_update(self, ctx: AgentContext) -> None:  # pragma: no cover - protocol
        ...

    def run_unwind(self, ctx: AgentContext) -> None:  # pragma: no cover - protocol
        ...


AGENTS: Dict[str, AgentModule] = {
    sentichain_eth.AGENT_NAME: sentichain_eth,
    sentichain_btc.AGENT_NAME: sentichain_btc,
}


def list_agent_names() -> List[str]:
    return list(AGENTS.keys())


def get_agent(name: str) -> AgentModule:
    return AGENTS[name]



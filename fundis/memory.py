from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .config import MEMORY_DB_PATH, ensure_data_dir


@dataclass
class Position:
    wallet_address: str
    agent_name: str
    ticker: str
    base_token: str
    quote_token: str
    allocated_amount: float  # in base token units (e.g. 10.0 USDC)
    allocated_amount_raw: int  # in smallest units (e.g. 10 * 10**decimals)
    current_position: str  # "USDC", "WBTC", "WETH"
    last_updated_at: str


class MemoryService:
    """
    Simple SQLite-backed memory for agents.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        ensure_data_dir()
        self.db_path = db_path or MEMORY_DB_PATH
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    # ------------------------------------------------------------------ #
    # Schema
    # ------------------------------------------------------------------ #
    def _init_schema(self) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet_address TEXT NOT NULL,
                agent_name TEXT NOT NULL,
                ticker TEXT NOT NULL,
                base_token TEXT NOT NULL,
                quote_token TEXT NOT NULL,
                allocated_amount REAL NOT NULL,
                allocated_amount_raw INTEGER NOT NULL,
                current_position TEXT NOT NULL,
                last_updated_at TEXT NOT NULL,
                UNIQUE(wallet_address, agent_name)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                wallet_address TEXT,
                agent_name TEXT,
                level TEXT NOT NULL,
                message TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    # ------------------------------------------------------------------ #
    # Logging
    # ------------------------------------------------------------------ #
    def log(
        self,
        message: str,
        level: str = "INFO",
        wallet_address: str | None = None,
        agent_name: str | None = None,
    ) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO logs (created_at, wallet_address, agent_name, level, message)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                wallet_address,
                agent_name,
                level,
                message,
            ),
        )
        self._conn.commit()

    # ------------------------------------------------------------------ #
    # Positions
    # ------------------------------------------------------------------ #
    def get_position(self, wallet_address: str, agent_name: str) -> Optional[Position]:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT wallet_address, agent_name, ticker, base_token, quote_token,
                   allocated_amount, allocated_amount_raw, current_position,
                   last_updated_at
            FROM positions
            WHERE wallet_address = ? AND agent_name = ?
            """,
            (wallet_address, agent_name),
        )
        row = cur.fetchone()
        if not row:
            return None
        return Position(
            wallet_address=row["wallet_address"],
            agent_name=row["agent_name"],
            ticker=row["ticker"],
            base_token=row["base_token"],
            quote_token=row["quote_token"],
            allocated_amount=row["allocated_amount"],
            allocated_amount_raw=row["allocated_amount_raw"],
            current_position=row["current_position"],
            last_updated_at=row["last_updated_at"],
        )

    def upsert_position(self, position: Position) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO positions (
                wallet_address, agent_name, ticker, base_token, quote_token,
                allocated_amount, allocated_amount_raw, current_position,
                last_updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(wallet_address, agent_name) DO UPDATE SET
                ticker = excluded.ticker,
                base_token = excluded.base_token,
                quote_token = excluded.quote_token,
                allocated_amount = excluded.allocated_amount,
                allocated_amount_raw = excluded.allocated_amount_raw,
                current_position = excluded.current_position,
                last_updated_at = excluded.last_updated_at
            """,
            (
                position.wallet_address,
                position.agent_name,
                position.ticker,
                position.base_token,
                position.quote_token,
                position.allocated_amount,
                position.allocated_amount_raw,
                position.current_position,
                position.last_updated_at,
            ),
        )
        self._conn.commit()

    def update_position_side(
        self,
        wallet_address: str,
        agent_name: str,
        new_side: str,
    ) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            UPDATE positions
            SET current_position = ?, last_updated_at = ?
            WHERE wallet_address = ? AND agent_name = ?
            """,
            (
                new_side,
                datetime.now(timezone.utc).isoformat(),
                wallet_address,
                agent_name,
            ),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()



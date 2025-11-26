from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from .config import MEMORY_DB_PATH, ensure_data_dir


@dataclass
class LogEntry:
    """A single log entry from agent communications."""

    id: int
    created_at: str
    wallet_address: str | None
    agent_name: str | None
    level: str
    message: str


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

    def get_logs(
        self,
        wallet_address: str | None = None,
        agent_name: str | None = None,
        level: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[LogEntry]:
        """
        Retrieve historical logs with optional filters.

        Args:
            wallet_address: Filter by wallet address (optional)
            agent_name: Filter by agent name (optional)
            level: Filter by log level (optional)
            limit: Maximum number of logs to return (default 50)
            offset: Number of logs to skip (for pagination)

        Returns:
            List of LogEntry objects, newest first
        """
        cur = self._conn.cursor()

        conditions = []
        params = []

        if wallet_address:
            conditions.append("wallet_address = ?")
            params.append(wallet_address)
        if agent_name:
            conditions.append("agent_name = ?")
            params.append(agent_name)
        if level:
            conditions.append("level = ?")
            params.append(level)

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        query = f"""
            SELECT id, created_at, wallet_address, agent_name, level, message
            FROM logs
            {where_clause}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])

        cur.execute(query, params)
        rows = cur.fetchall()

        return [
            LogEntry(
                id=row["id"],
                created_at=row["created_at"],
                wallet_address=row["wallet_address"],
                agent_name=row["agent_name"],
                level=row["level"],
                message=row["message"],
            )
            for row in rows
        ]

    def get_log_count(
        self,
        wallet_address: str | None = None,
        agent_name: str | None = None,
        level: str | None = None,
    ) -> int:
        """Get total count of logs matching filters."""
        cur = self._conn.cursor()

        conditions = []
        params = []

        if wallet_address:
            conditions.append("wallet_address = ?")
            params.append(wallet_address)
        if agent_name:
            conditions.append("agent_name = ?")
            params.append(agent_name)
        if level:
            conditions.append("level = ?")
            params.append(level)

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        query = f"SELECT COUNT(*) as cnt FROM logs {where_clause}"
        cur.execute(query, params)
        row = cur.fetchone()
        return row["cnt"] if row else 0

    def get_distinct_agents(self) -> List[str]:
        """Get list of distinct agent names that have logs."""
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT DISTINCT agent_name FROM logs
            WHERE agent_name IS NOT NULL
            ORDER BY agent_name
            """
        )
        return [row["agent_name"] for row in cur.fetchall()]

    def clear_logs(
        self,
        wallet_address: str | None = None,
        agent_name: str | None = None,
    ) -> int:
        """
        Clear logs matching filters. Returns number of deleted rows.

        If no filters provided, clears ALL logs.
        """
        cur = self._conn.cursor()

        conditions = []
        params = []

        if wallet_address:
            conditions.append("wallet_address = ?")
            params.append(wallet_address)
        if agent_name:
            conditions.append("agent_name = ?")
            params.append(agent_name)

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        query = f"DELETE FROM logs {where_clause}"
        cur.execute(query, params)
        deleted = cur.rowcount
        self._conn.commit()
        return deleted

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

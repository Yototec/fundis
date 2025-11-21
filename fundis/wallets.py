from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from eth_account import Account

from .config import WALLET_STORE_PATH, ensure_data_dir


@dataclass
class Wallet:
    name: str
    address: str
    private_key: str
    created_at: str


class WalletStore:
    """
    Local wallet store backed by a JSON file.

    NOTE: private keys are stored unencrypted for simplicity.
    Do not use production keys with this store.
    """

    def __init__(self, path: Path | None = None) -> None:
        ensure_data_dir()
        self.path = path or WALLET_STORE_PATH
        self._wallets: List[Wallet] = []
        self._load()

    # --------------------------------------------------------------------- #
    # Internal helpers
    # --------------------------------------------------------------------- #
    def _load(self) -> None:
        if not self.path.exists():
            self._wallets = []
            return
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self._wallets = [
            Wallet(
                name=w["name"],
                address=w["address"],
                private_key=w["private_key"],
                created_at=w.get("created_at", ""),
            )
            for w in data.get("wallets", [])
        ]

    def _save(self) -> None:
        payload = {
            "wallets": [
                {
                    "name": w.name,
                    "address": w.address,
                    "private_key": w.private_key,
                    "created_at": w.created_at,
                }
                for w in self._wallets
            ]
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #
    @property
    def wallets(self) -> List[Wallet]:
        return list(self._wallets)

    def add_wallet(self, private_key: str, name: Optional[str] = None) -> Wallet:
        key = private_key.strip()
        if key.startswith("0x") or key.startswith("0X"):
            key = key[2:]
        acct = Account.from_key(bytes.fromhex(key))
        address = acct.address
        if not name:
            name = f"wallet-{len(self._wallets) + 1}"
        wallet = Wallet(
            name=name,
            address=address,
            private_key="0x" + key,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self._wallets.append(wallet)
        self._save()
        return wallet

    def delete_wallet(self, index: int) -> Wallet:
        wallet = self._wallets.pop(index)
        self._save()
        return wallet

    def get_wallet(self, index: int) -> Wallet:
        return self._wallets[index]

    def export_private_key(self, index: int) -> str:
        return self._wallets[index].private_key



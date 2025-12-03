from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .config import DATA_DIR, ensure_data_dir


AUTH_FILE: Path = DATA_DIR / "auth.json"


@dataclass
class AuthConfig:
    sentichain_api_key: Optional[str] = None


def load_auth_config() -> Optional[AuthConfig]:
    """
    Load the local auth configuration, if present.

    The file is stored as plain JSON at ~/.fundis/auth.json.
    """
    ensure_data_dir()
    if not AUTH_FILE.exists():
        return None
    try:
        data = json.loads(AUTH_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None

    key_raw = data.get("sentichain_api_key") or ""
    key = key_raw.strip() or None if isinstance(key_raw, str) else None

    if not key:
        return None

    return AuthConfig(sentichain_api_key=key)


def _write_auth_config(cfg: AuthConfig) -> None:
    ensure_data_dir()
    payload = {}
    if cfg.sentichain_api_key:
        payload["sentichain_api_key"] = cfg.sentichain_api_key
    AUTH_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def save_sentichain_api_key(api_key: str) -> AuthConfig:
    """
    Persist the SentiChain API key locally.

    NOTE: the key is stored in plain text. Do not use secrets you are not
    comfortable storing on this machine as-is.
    """
    cfg = AuthConfig(sentichain_api_key=api_key.strip())
    _write_auth_config(cfg)
    return cfg


def clear_auth_config() -> None:
    """Delete the local auth file, if it exists."""
    ensure_data_dir()
    try:
        AUTH_FILE.unlink()
    except FileNotFoundError:
        pass

"""Credential loading for optional market-data providers."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values


def get_tushare_token(env_file: str | Path | None = None) -> str:
    """Return the Tushare token, preferring the process environment."""

    token = os.getenv("TUSHARE_TOKEN", "").strip()
    token_file = Path(env_file) if env_file is not None else None
    if not token and token_file is not None and token_file.is_file():
        token = str(dotenv_values(token_file).get("TUSHARE_TOKEN") or "").strip()
    if not token:
        raise ValueError(
            "TUSHARE_TOKEN is not configured. Set the environment variable or fill "
            f"{token_file or 'an explicit env file'}."
        )
    return token


def get_fred_key(env_file: str | Path | None = None) -> str:
    """Return the FRED API key, preferring the process environment."""

    key = os.getenv("FRED_KEY", "").strip()
    key_file = Path(env_file) if env_file is not None else None
    if not key and key_file is not None and key_file.is_file():
        key = str(dotenv_values(key_file).get("FRED_KEY") or "").strip()
    if not key:
        raise ValueError(
            "FRED_KEY is not configured. Set the environment variable or fill "
            f"{key_file or 'an explicit env file'}."
        )
    return key

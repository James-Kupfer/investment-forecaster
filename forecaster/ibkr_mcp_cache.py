"""
IBKR MCP price cache — read-only from Python's perspective.

The cache is populated by Claude via the IBKR MCP tools (search_contracts +
get_price_history) and written to ibkr_price_cache.json. Python reads it as the
highest-priority data source in MarketDataFetcher, before the Client Portal REST
API and Yahoo Finance fallback.

Cache entries expire after MAX_AGE_HOURS. When stale or absent, the pipeline
falls through to the next source.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

_CACHE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ibkr_price_cache.json")
MAX_AGE_HOURS = 25  # a bit over one trading day


def _load() -> dict:
    try:
        with open(_CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def get_ohlcv(symbol: str) -> Optional[pd.DataFrame]:
    """Return cached OHLCV DataFrame for *symbol*, or None if absent/stale."""
    cache = _load()
    entry = cache.get(symbol)
    if not entry or not entry.get("bars"):
        return None

    fetched_at = datetime.fromisoformat(entry["fetched_at"].replace("Z", "+00:00"))
    age_hours = (datetime.now(timezone.utc) - fetched_at).total_seconds() / 3600
    if age_hours > MAX_AGE_HOURS:
        logger.debug("ibkr_mcp_cache: stale entry for %s (%.1fh old)", symbol, age_hours)
        return None

    bars = entry["bars"]
    df = pd.DataFrame(bars)
    df.index = pd.DatetimeIndex(pd.to_datetime(df.pop("date")))
    df.columns = [c.capitalize() for c in df.columns]
    return df if not df.empty else None

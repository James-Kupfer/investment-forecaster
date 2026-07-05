"""
Market data fetching: IBKR Client Portal API (primary) with yfinance fallback.

IBKR_GATEWAY_URL env var sets the Client Portal Gateway base URL
(default https://localhost:5000). The gateway uses a self-signed TLS cert;
InsecureRequestWarning is suppressed module-wide.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import pandas as pd
import urllib3
import yfinance as yf

logger = logging.getLogger(__name__)

_IBKR_BASE = os.getenv("IBKR_GATEWAY_URL", "https://localhost:5000")

# MCP enum names → IBKR REST API period strings
_PERIOD_MAP: dict[str, str] = {
    "ONE_DAY":       "1d",
    "TWO_DAYS":      "2d",
    "THREE_DAYS":    "3d",
    "ONE_WEEK":      "1w",
    "TWO_WEEKS":     "2w",
    "ONE_MONTH":     "1m",
    "THREE_MONTHS":  "3m",
    "SIX_MONTHS":    "6m",
    "ONE_YEAR":      "1y",
    "TWO_YEARS":     "2y",
    "FIVE_YEARS":    "5y",
}

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class IbkrClient:
    """Thin wrapper around the IBKR Client Portal REST API."""

    def __init__(self) -> None:
        import requests
        self._session = requests.Session()
        self._session.verify = False
        self._contract_cache: dict[tuple[str, str], Optional[int]] = {}

    def resolve_contract(self, symbol: str, sec_type: str = "STK") -> Optional[int]:
        """Return IBKR conid for symbol/sec_type, or None if not found."""
        key = (symbol, sec_type)
        if key in self._contract_cache:
            return self._contract_cache[key]
        try:
            resp = self._session.post(
                f"{_IBKR_BASE}/v1/api/iserver/secdef/search",
                json={"symbol": symbol, "secType": sec_type},
                timeout=10,
            )
            resp.raise_for_status()
            contracts = resp.json()
            conid = int(contracts[0]["conid"]) if contracts else None
        except Exception as exc:
            logger.debug("IBKR contract lookup failed %s (%s): %s", symbol, sec_type, exc)
            conid = None
        self._contract_cache[key] = conid
        return conid

    def fetch_ohlcv(
        self,
        symbol: str,
        ibkr_period: str = "SIX_MONTHS",
        sec_type: str = "STK",
    ) -> Optional[pd.DataFrame]:
        """Fetch daily OHLCV bars from IBKR. Returns DataFrame or None on any failure."""
        conid = self.resolve_contract(symbol, sec_type)
        if conid is None:
            return None
        period_str = _PERIOD_MAP.get(ibkr_period, "6m")
        try:
            resp = self._session.get(
                f"{_IBKR_BASE}/v1/api/iserver/marketdata/history",
                params={"conid": conid, "period": period_str, "bar": "1d", "outsideRth": "false"},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json().get("data") or []
            if not data:
                return None
            df = pd.DataFrame([
                {
                    "Date":   pd.Timestamp(bar["t"], unit="ms"),
                    "Open":   bar.get("o"),
                    "High":   bar.get("h"),
                    "Low":    bar.get("l"),
                    "Close":  bar.get("c"),
                    "Volume": bar.get("v", 0),
                }
                for bar in data
            ]).set_index("Date")
            df.index = pd.DatetimeIndex(df.index)
            return df if not df.empty else None
        except Exception as exc:
            logger.debug("IBKR history failed %s (conid=%s): %s", symbol, conid, exc)
            return None


# Module-level singleton so the contract cache persists across agents within one pipeline run.
_ibkr = IbkrClient()


class MarketDataFetcher:
    """IBKR-primary data fetcher with transparent yfinance fallback."""

    def fetch_ohlcv(
        self,
        symbol: str,
        period_yf: str = "6mo",
        ibkr_period: str = "SIX_MONTHS",
        sec_type: str = "STK",
    ) -> pd.DataFrame:
        """
        Return daily OHLCV DataFrame. Tries IBKR first; falls back to yfinance.
        Raises ValueError if both sources fail.
        """
        df = _ibkr.fetch_ohlcv(symbol, ibkr_period=ibkr_period, sec_type=sec_type)
        if df is not None and not df.empty:
            logger.debug("market_data: IBKR OK for %s", symbol)
            return df
        logger.debug("market_data: IBKR unavailable for %s, using yfinance", symbol)
        df = yf.Ticker(symbol).history(period=period_yf)
        if df.empty:
            raise ValueError(f"No price data for {symbol} from IBKR or yfinance")
        return df

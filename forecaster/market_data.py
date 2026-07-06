"""
Market data fetching: IBKR Client Portal API (primary) with Yahoo Finance direct fallback.

IBKR_GATEWAY_URL env var sets the Client Portal Gateway base URL
(default https://localhost:5000). The gateway uses a self-signed TLS cert;
InsecureRequestWarning is suppressed module-wide.

Yahoo Finance fallback hits query1.finance.yahoo.com directly (v8 chart API) instead
of yfinance, which requires fc.yahoo.com for its cookie handshake — a host that does
not resolve on this network.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
from typing import Optional

import pandas as pd
import urllib3

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


def _fetch_yahoo_ohlcv(symbol: str, period: str = "6mo") -> Optional[pd.DataFrame]:
    """Fetch daily OHLCV from query1.finance.yahoo.com (bypasses fc.yahoo.com crumb)."""
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.request.quote(symbol)}"
        f"?range={period}&interval=1d&events=div%2Csplit"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    last_err: Optional[Exception] = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.load(resp)
            break
        except Exception as exc:
            last_err = exc
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
    else:
        logger.debug("Yahoo direct fetch failed for %s: %s", symbol, last_err)
        return None

    chart = payload.get("chart") or {}
    if chart.get("error"):
        logger.debug("Yahoo error for %s: %s", symbol, chart["error"])
        return None
    results = chart.get("result")
    if not results:
        return None
    result = results[0]

    timestamps = result.get("timestamp")
    if not timestamps:
        return None

    quote = (result.get("indicators", {}).get("quote") or [{}])[0]
    adj_block = (result.get("indicators", {}).get("adjclose") or [{}])[0]
    adjclose = adj_block.get("adjclose")
    gmt_offset = result.get("meta", {}).get("gmtoffset", 0) or 0

    rows = []
    for i, ts in enumerate(timestamps):
        date_idx = pd.Timestamp(ts + gmt_offset, unit="s", tz="UTC").tz_localize(None).normalize()
        close = (adjclose[i] if adjclose and i < len(adjclose) else None) or (
            quote.get("close", [])[i] if i < len(quote.get("close", [])) else None
        )
        if close is None:
            continue
        rows.append({
            "Date": date_idx,
            "Open": (quote.get("open") or [])[i] if i < len(quote.get("open") or []) else None,
            "High": (quote.get("high") or [])[i] if i < len(quote.get("high") or []) else None,
            "Low": (quote.get("low") or [])[i] if i < len(quote.get("low") or []) else None,
            "Close": close,
            "Volume": (quote.get("volume") or [])[i] if i < len(quote.get("volume") or []) else 0,
        })

    if not rows:
        return None
    df = pd.DataFrame(rows).set_index("Date")
    df.index = pd.DatetimeIndex(df.index)
    return df if not df.empty else None


class MarketDataFetcher:
    """IBKR-primary data fetcher with direct Yahoo Finance fallback."""

    def fetch_ohlcv(
        self,
        symbol: str,
        period_yf: str = "6mo",
        ibkr_period: str = "SIX_MONTHS",
        sec_type: str = "STK",
        yahoo_symbol: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Return daily OHLCV DataFrame. Tries IBKR first; falls back to Yahoo direct API.

        yahoo_symbol overrides symbol for the Yahoo fallback — needed when the IBKR
        ticker differs from the Yahoo ticker (e.g. IBKR="VIX" / Yahoo="^VIX").
        Raises ValueError if both sources fail.
        """
        from forecaster.ibkr_mcp_cache import get_ohlcv as _mcp_cached
        df = _mcp_cached(symbol)
        if df is not None and not df.empty:
            logger.debug("market_data: MCP cache hit for %s", symbol)
            return df
        df = _ibkr.fetch_ohlcv(symbol, ibkr_period=ibkr_period, sec_type=sec_type)
        if df is not None and not df.empty:
            logger.debug("market_data: IBKR Client Portal OK for %s", symbol)
            return df
        yf_sym = yahoo_symbol or symbol
        logger.debug("market_data: IBKR unavailable for %s, using Yahoo direct (%s)", symbol, yf_sym)
        df = _fetch_yahoo_ohlcv(yf_sym, period=period_yf)
        if df is not None and not df.empty:
            return df
        raise ValueError(f"No price data for {symbol} from IBKR or Yahoo")

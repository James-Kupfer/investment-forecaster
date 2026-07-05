"""
TA-Lib preprocessing: OHLCV → human-readable indicator descriptions.

Fetches price history via MarketDataFetcher (IBKR primary, yfinance fallback),
computes indicators via TA-Lib (if installed), and returns plain-English
descriptions suitable for LLM context. Falls back to pandas-based calculations
when TA-Lib is not available.
"""
from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

from forecaster.market_data import MarketDataFetcher

logger = logging.getLogger(__name__)

try:
    import talib
    _TALIB_AVAILABLE = True
except ImportError:
    _TALIB_AVAILABLE = False
    logger.warning("TA-Lib not installed — using pandas-based indicator fallbacks")


def fetch_ohlcv(symbol: str, period: str = "6mo") -> pd.DataFrame:
    """Return OHLCV DataFrame. IBKR primary, yfinance fallback."""
    return MarketDataFetcher().fetch_ohlcv(
        symbol, period_yf=period, ibkr_period="SIX_MONTHS"
    )


def describe_rsi(df: pd.DataFrame, period: int = 14) -> str:
    close = df["Close"].values
    if _TALIB_AVAILABLE:
        rsi_series = talib.RSI(close, timeperiod=period)
        rsi = rsi_series[-1]
    else:
        delta = df["Close"].diff()
        gain = delta.clip(lower=0).rolling(period).mean()
        loss = (-delta.clip(upper=0)).rolling(period).mean()
        rs = gain / loss.replace(0, float("inf"))
        rsi = (100 - 100 / (1 + rs)).iloc[-1]

    if pd.isna(rsi):
        return "RSI unavailable (insufficient history)"
    if rsi >= 70:
        return f"RSI {rsi:.1f} — overbought territory"
    if rsi <= 30:
        return f"RSI {rsi:.1f} — oversold territory"
    return f"RSI {rsi:.1f} — neutral"


def describe_macd(df: pd.DataFrame) -> str:
    close = df["Close"].values
    if _TALIB_AVAILABLE:
        macd, signal, hist = talib.MACD(close, fastperiod=12, slowperiod=26, signalperiod=9)
    else:
        ema12 = df["Close"].ewm(span=12, adjust=False).mean()
        ema26 = df["Close"].ewm(span=26, adjust=False).mean()
        macd_s = ema12 - ema26
        signal_s = macd_s.ewm(span=9, adjust=False).mean()
        hist_s = macd_s - signal_s
        macd, signal, hist = macd_s.values, signal_s.values, hist_s.values

    if pd.isna(macd[-1]) or pd.isna(signal[-1]):
        return "MACD unavailable (insufficient history)"
    direction = "bullish" if hist[-1] > 0 else "bearish"
    crossing = ""
    if len(hist) >= 2 and not pd.isna(hist[-2]):
        if hist[-2] <= 0 < hist[-1]:
            crossing = " (bullish crossover)"
        elif hist[-2] >= 0 > hist[-1]:
            crossing = " (bearish crossover)"
    return f"MACD {direction}{crossing} — histogram {hist[-1]:+.3f}"


def describe_ma_alignment(df: pd.DataFrame) -> str:
    close = df["Close"]
    ma20 = close.rolling(20).mean().iloc[-1]
    ma50 = close.rolling(50).mean().iloc[-1]
    ma200 = close.rolling(200).mean().iloc[-1]
    price = close.iloc[-1]

    levels = {"price": price, "MA20": ma20, "MA50": ma50, "MA200": ma200}
    known = {k: v for k, v in levels.items() if not pd.isna(v)}
    ranked = sorted(known, key=lambda k: known[k], reverse=True)
    alignment = " > ".join(ranked)

    if all(k in known for k in ("price", "MA20", "MA50")):
        if price > ma20 > ma50:
            trend = "bullish stack"
        elif price < ma20 < ma50:
            trend = "bearish stack"
        else:
            trend = "mixed"
    else:
        trend = "insufficient data"
    return f"MA alignment ({trend}): {alignment}"


def describe_adx(df: pd.DataFrame, period: int = 14) -> str:
    if _TALIB_AVAILABLE:
        adx_series = talib.ADX(
            df["High"].values, df["Low"].values, df["Close"].values, timeperiod=period
        )
        adx = adx_series[-1]
    else:
        high, low, close = df["High"], df["Low"], df["Close"]
        tr = pd.concat(
            [high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1
        ).max(axis=1)
        atr = tr.rolling(period).mean()
        adx = (atr.iloc[-1] / close.iloc[-1] * 100) if close.iloc[-1] != 0 else float("nan")

    if pd.isna(adx):
        return "ADX unavailable (insufficient history)"
    if adx >= 40:
        return f"ADX {adx:.1f} — very strong trend"
    if adx >= 25:
        return f"ADX {adx:.1f} — trending"
    return f"ADX {adx:.1f} — weak/no trend"


def describe_volume(df: pd.DataFrame, lookback: int = 20) -> str:
    vol = df["Volume"]
    avg = vol.rolling(lookback).mean().iloc[-1]
    current = vol.iloc[-1]
    if pd.isna(avg) or avg == 0:
        return "Volume data unavailable"
    ratio = current / avg
    if ratio >= 2.0:
        return f"Volume {ratio:.1f}x average — significantly elevated"
    if ratio >= 1.25:
        return f"Volume {ratio:.1f}x average — above average"
    if ratio <= 0.5:
        return f"Volume {ratio:.1f}x average — very light"
    return f"Volume {ratio:.1f}x average — normal"


def get_technical_context(symbol: str, period: str = "6mo") -> dict[str, str]:
    """
    Return a dict of indicator_name → plain-English description for *symbol*.
    Raises ValueError if price data cannot be fetched.
    """
    df = fetch_ohlcv(symbol, period=period)
    return {
        "rsi": describe_rsi(df),
        "macd": describe_macd(df),
        "ma_alignment": describe_ma_alignment(df),
        "adx": describe_adx(df),
        "volume": describe_volume(df),
    }

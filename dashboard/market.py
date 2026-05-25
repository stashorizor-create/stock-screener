"""
Market overview data for the dashboard:
  - Sector ETF performance (1W / 1M / 6M / 1Y) via yfinance
  - Hot themes loaded from themes/hot_themes.json
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

SECTOR_ETFS: dict[str, str] = {
    "Technology":       "XLK",
    "Energy":           "XLE",
    "Financials":       "XLF",
    "Healthcare":       "XLV",
    "Industrials":      "XLI",
    "Consumer Disc.":   "XLY",
    "Consumer Staples": "XLP",
    "Utilities":        "XLU",
    "Real Estate":      "XLRE",
    "Materials":        "XLB",
    "Communication":    "XLC",
    "Semiconductors":   "SOXX",
    "Biotech":          "XBI",
    "Clean Energy":     "ICLN",
    "Cyber Security":   "HACK",
    "AI & Robotics":    "BOTZ",
}

PERIODS = {"1W": 5, "1M": 21, "6M": 126, "1Y": 252}


def fetch_sector_returns() -> pd.DataFrame:
    """
    Returns a DataFrame with sector returns over 1W, 1M, 6M, 1Y.
    Columns: Sector, ETF, 1W, 1M, 6M, 1Y (all as floats, e.g. 0.05 = 5%).
    Returns empty DataFrame on failure.
    """
    try:
        import yfinance as yf
    except ImportError:
        logger.warning("yfinance not installed")
        return pd.DataFrame()

    tickers = list(SECTOR_ETFS.values())
    try:
        raw = yf.download(tickers, period="1y", auto_adjust=True, progress=False)
        prices = raw["Close"] if "Close" in raw.columns else raw
    except Exception as exc:
        logger.warning("yfinance sector download failed: %s", exc)
        return pd.DataFrame()

    rows = []
    for sector, ticker in SECTOR_ETFS.items():
        col = prices.get(ticker)
        if col is None:
            continue
        col = col.dropna()
        if len(col) < 10:
            continue
        row: dict = {"Sector": sector, "ETF": ticker}
        for label, days in PERIODS.items():
            if len(col) >= days + 1:
                row[label] = col.iloc[-1] / col.iloc[-days - 1] - 1
            else:
                row[label] = None
        rows.append(row)

    return pd.DataFrame(rows) if rows else pd.DataFrame()

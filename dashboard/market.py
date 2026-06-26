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


def fetch_sector_history(period: str = "2y") -> dict[str, pd.Series]:
    """
    Daily close history per sector ETF (default 2y so the 200-day SMA is complete
    across a 1-year chart view). Returns {sector_name: close Series}. Empty on failure.
    """
    try:
        import yfinance as yf
    except ImportError:
        logger.warning("yfinance not installed")
        return {}

    tickers = list(SECTOR_ETFS.values())
    try:
        raw = yf.download(tickers, period=period, auto_adjust=True, progress=False)
        prices = raw["Close"] if "Close" in raw.columns else raw
    except Exception as exc:
        logger.warning("yfinance sector history download failed: %s", exc)
        return {}

    out: dict[str, pd.Series] = {}
    for sector, ticker in SECTOR_ETFS.items():
        col = prices.get(ticker)
        if col is None:
            continue
        col = col.dropna()
        if len(col) >= 60:
            out[sector] = col
    return out


def minervini_stage(close: pd.Series) -> dict:
    """
    Minervini Trend Template (Stage Analysis) for a price series.
    Returns the 50/150/200-day SMAs plus a 0-7 score, a stage label, and a colour.

    Criteria (sector-adapted; RS-vs-market line omitted):
      1. price above 150d & 200d SMA   2. 150d > 200d   3. 200d rising (~1mo)
      4. 50d > 150d > 200d             5. price > 50d
      6. >=30% above 52w low           7. within 25% of 52w high
    """
    blank = {"score": 0, "label": "n/a", "color": "#7d8590", "pass": False,
             "sma50": None, "sma150": None, "sma200": None}
    if close is None or len(close) < 200:
        return blank

    sma50 = close.rolling(50).mean()
    sma150 = close.rolling(150).mean()
    sma200 = close.rolling(200).mean()
    px = float(close.iloc[-1])
    s50, s150, s200 = float(sma50.iloc[-1]), float(sma150.iloc[-1]), float(sma200.iloc[-1])
    s200_prev = float(sma200.iloc[-21]) if sma200.notna().sum() > 21 else s200
    win = close.iloc[-252:] if len(close) >= 252 else close
    hi52, lo52 = float(win.max()), float(win.min())

    crit = [
        px > s150 and px > s200,
        s150 > s200,
        s200 > s200_prev,
        s50 > s150 and s50 > s200,
        px > s50,
        lo52 > 0 and px >= 1.30 * lo52,
        hi52 > 0 and px >= 0.75 * hi52,
    ]
    score = int(sum(bool(c) for c in crit))
    if score >= 6:
        label, color = "Stage 2 ↑", "#3fb950"
    elif score >= 4:
        label, color = "Setting up", "#e3b341"
    else:
        label, color = ("Stage 4 ↓" if px < s200 else "Stage 1 —"), "#f85149"

    return {"score": score, "label": label, "color": color, "pass": score == 7,
            "sma50": sma50, "sma150": sma150, "sma200": sma200}

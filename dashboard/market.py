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


# ---------------------------------------------------------------------------
# Entry-regime flag  ("positions fare worse when market < SMA50 AND the sector
# is rolling over").  Combines a market-wide check (QQQ vs its 50-day SMA) with
# a per-sector check (the stock's SPDR sector ETF's 20-day SMA sloping down).
# ---------------------------------------------------------------------------

# Borsdata sectorId (see /sectors) → SPDR sector ETF. Borsdata folds Real Estate
# into the Finance sector (id 1); real-estate branches are split out to XLRE below.
SECTOR_ID_TO_ETF: dict[int, str] = {
    1:  "XLF",   # Finans & Fastighet   (Financials; REIT branches → XLRE)
    2:  "XLP",   # Dagligvaror          (Consumer Staples)
    3:  "XLE",   # Energi               (Energy)
    4:  "XLV",   # Hälsovård            (Healthcare)
    5:  "XLI",   # Industri             (Industrials)
    6:  "XLK",   # Informationsteknik   (Information Technology)
    7:  "XLB",   # Material             (Materials)
    8:  "XLY",   # Sällanköpsvaror      (Consumer Discretionary)
    9:  "XLC",   # Telekommunikation    (Communication Services)
    10: "XLU",   # Kraftförsörjning     (Utilities)
}
SECTOR_ID_TO_NAME: dict[int, str] = {
    1:  "Financials",       2: "Consumer Staples", 3: "Energy",         4: "Healthcare",
    5:  "Industrials",      6: "Technology",       7: "Materials",      8: "Consumer Disc.",
    9:  "Communication",   10: "Utilities",
}
_REIT_BRANCH_IDS = {75, 76}   # Fastighetsbolag / Fastighet-REIT → real estate


def sector_name_for(sector_id) -> str | None:
    """English GICS-style sector name for a Borsdata sectorId."""
    try:
        return SECTOR_ID_TO_NAME.get(int(sector_id)) if sector_id is not None else None
    except (TypeError, ValueError):
        return None
_REGIME_SECTOR_ETFS = ["XLK", "XLE", "XLF", "XLV", "XLI",
                       "XLY", "XLP", "XLU", "XLRE", "XLB", "XLC"]
_MARKET_ETF = "QQQ"
_SECTOR_SLOPE_THRESHOLD = -0.002   # -0.2% average daily slope of the 20-day SMA


def sector_etf_for(sector_id, branch_id=None) -> str | None:
    """Map a Borsdata sectorId (+ optional branchId) to its SPDR sector ETF."""
    if sector_id is None:
        return None
    try:
        sid = int(sector_id)
    except (TypeError, ValueError):
        return None
    if sid == 1 and branch_id is not None:
        try:
            if int(branch_id) in _REIT_BRANCH_IDS:
                return "XLRE"
        except (TypeError, ValueError):
            pass
    return SECTOR_ID_TO_ETF.get(sid)


def compute_entry_regime() -> dict:
    """
    Market + per-sector regime used for the watchlist "unfavorable entry" flag.

    Returns a dict:
      market_weak: bool | None   — QQQ closes below its 50-day SMA
      qqq_close / qqq_sma50: floats (for display)
      sector_slope: {etf: 5-day avg daily slope of the ETF's 20-day SMA}
      sector_weak:  {etf: slope < -0.2%/day}
    Returns {} on data failure (caller treats as "no flag / unknown").
    """
    try:
        import yfinance as yf
    except ImportError:
        logger.warning("yfinance not installed — entry regime unavailable")
        return {}

    tickers = [_MARKET_ETF] + _REGIME_SECTOR_ETFS
    try:
        raw = yf.download(tickers, period="6mo", auto_adjust=True, progress=False)
        prices = raw["Close"] if "Close" in raw.columns else raw
    except Exception as exc:
        logger.warning("entry-regime download failed: %s", exc)
        return {}

    out: dict = {"market_weak": None, "sector_weak": {}, "sector_slope": {}}

    q = prices.get(_MARKET_ETF)
    if q is not None:
        q = q.dropna()
        if len(q) >= 50:
            sma50 = float(q.rolling(50).mean().iloc[-1])
            out["qqq_close"] = float(q.iloc[-1])
            out["qqq_sma50"] = sma50
            out["market_weak"] = bool(float(q.iloc[-1]) < sma50)

    for etf in _REGIME_SECTOR_ETFS:
        col = prices.get(etf)
        if col is None:
            continue
        col = col.dropna()
        if len(col) < 25:                        # need 20-SMA + 5-day lookback
            continue
        sma20 = col.rolling(20).mean()
        s_now, s_prev = sma20.iloc[-1], sma20.iloc[-6]
        if pd.isna(s_now) or pd.isna(s_prev) or s_prev <= 0:
            continue
        slope = (float(s_now) / float(s_prev)) ** (1 / 5) - 1   # avg daily over 5d
        out["sector_slope"][etf] = slope
        out["sector_weak"][etf] = bool(slope < _SECTOR_SLOPE_THRESHOLD)

    return out


def entry_regime_flag(sector_etf: str | None, regime: dict) -> dict:
    """
    Combine the market-wide check with this stock's sector into the entry flag.
    `unfavorable` is True only when BOTH the market is weak (QQQ < SMA50) AND the
    stock's sector ETF is rolling over (20-day SMA slope < -0.2%/day) — the regime
    the trading diary flagged as producing worse entries.
    """
    market_weak = regime.get("market_weak") if regime else None
    sector_weak = (regime.get("sector_weak", {}).get(sector_etf)
                   if (regime and sector_etf) else None)
    sector_slope = (regime.get("sector_slope", {}).get(sector_etf)
                    if (regime and sector_etf) else None)
    return {
        "unfavorable":  bool(market_weak) and bool(sector_weak),
        "market_weak":  market_weak,
        "sector_weak":  sector_weak,
        "sector_etf":   sector_etf,
        "sector_slope": sector_slope,
    }

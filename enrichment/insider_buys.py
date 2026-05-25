"""
Insider buy detector.

US stocks:  SEC EDGAR Form 4 filings (free, official, no API key needed).
Nordic:     Not currently available via free API. Returns None gracefully.

Returns days_since_last_buy (int) or None if no recent buy found / unavailable.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

import requests

logger = logging.getLogger(__name__)

_SESSION = requests.Session()
_SESSION.headers["User-Agent"] = "stock-screener stashorizor@gmail.com"

EDGAR_SEARCH = "https://efts.sec.gov/LATEST/search-index"


def get_insider_buys_us(symbol: str, lookback_days: int = 180) -> int | None:
    """
    Search SEC EDGAR Form 4 filings for recent insider purchases.
    Returns days since the most recent buy, or None if none found.
    """
    start = (date.today() - timedelta(days=lookback_days)).isoformat()
    end   = date.today().isoformat()

    try:
        resp = _SESSION.get(
            EDGAR_SEARCH,
            params={
                "q":         f'"{symbol}"',
                "forms":     "4",
                "dateRange": "custom",
                "startdt":   start,
                "enddt":     end,
            },
            timeout=15,
        )
        resp.raise_for_status()
        hits = resp.json().get("hits", {}).get("hits", [])
    except Exception as exc:
        logger.warning("EDGAR fetch failed for %s: %s", symbol, exc)
        return None

    if not hits:
        return None

    # Most recent filing first (EDGAR returns sorted by date desc)
    latest = hits[0].get("_source", {})
    file_date_str = latest.get("file_date", "")
    if not file_date_str:
        return None

    try:
        filed = date.fromisoformat(file_date_str)
        return (date.today() - filed).days
    except Exception:
        return None


def get_insider_buys_nordic(symbol: str, lookback_days: int = 180) -> int | None:
    """
    Nordic insider buy lookup. Currently returns None — the Swedish FI registry
    (marknadssok.fi.se) API endpoint structure needs investigation.
    Norway/Denmark/Finland have no accessible free API.
    """
    return None


def get_insider_buys(symbol: str, exchange: str, lookback_days: int = 180) -> int | None:
    """
    Route to the correct source based on exchange.
    Returns days since most recent insider buy, or None.
    """
    if exchange in ("NYSE", "NASDAQ"):
        return get_insider_buys_us(symbol, lookback_days)
    else:
        return get_insider_buys_nordic(symbol, lookback_days)

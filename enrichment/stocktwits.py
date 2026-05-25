"""
StockTwits mention counter (free public API, no credentials required).

Counts messages about a symbol posted in the last 24 hours.
Rate limit: ~200 requests/hour unauthenticated.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

import requests

logger = logging.getLogger(__name__)

_SESSION = requests.Session()
_SESSION.headers["User-Agent"] = "Mozilla/5.0"


def get_mention_count(symbol: str, lookback_hours: int = 24) -> int | None:
    """
    Return the number of StockTwits messages about symbol in the last lookback_hours.
    Returns None on failure.
    """
    try:
        url = f"https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json"
        resp = _SESSION.get(url, timeout=10)
        resp.raise_for_status()
        messages = resp.json().get("messages", [])
    except Exception as exc:
        logger.warning("StockTwits fetch failed for %s: %s", symbol, exc)
        return None

    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    count = 0
    for msg in messages:
        created_raw = msg.get("created_at", "")
        try:
            created = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
            if created >= cutoff:
                count += 1
        except Exception:
            pass

    return count


def get_trending_symbols(limit: int = 30) -> list[str]:
    """Return a list of currently trending ticker symbols on StockTwits."""
    try:
        resp = _SESSION.get(
            "https://api.stocktwits.com/api/2/trending/symbols.json",
            timeout=10,
        )
        resp.raise_for_status()
        symbols = resp.json().get("symbols", [])
        return [s["symbol"] for s in symbols[:limit]]
    except Exception as exc:
        logger.warning("StockTwits trending fetch failed: %s", exc)
        return []

"""
Google Trends acceleration fetcher via pytrends (no credentials required).

Returns a float representing week-over-week change in search interest:
  positive = rising, negative = falling, None = unavailable.
"""
from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)


def get_trends_acceleration(keyword: str, geo: str = "") -> float | None:
    """
    Compare average Google Trends interest in the last 7 days vs the prior 7 days.
    Returns (recent - prior) / prior, clamped to [-1, 1], or None on failure.

    Args:
        keyword: Search term (company name works better than ticker for non-US stocks).
        geo:     ISO country code to restrict results (e.g. "SE"). Empty = worldwide.
    """
    try:
        from pytrends.request import TrendReq
    except ImportError:
        logger.warning("pytrends not installed — Google Trends unavailable")
        return None

    try:
        pt = TrendReq(hl="en-US", tz=0, timeout=(10, 30))
        pt.build_payload([keyword], timeframe="today 1-m", geo=geo)
        df = pt.interest_over_time()

        if df.empty or keyword not in df.columns:
            return None

        vals = df[keyword].values.astype(float)
        if len(vals) < 14:
            return None

        recent = vals[-7:].mean()
        prior  = vals[-14:-7].mean()

        if prior == 0:
            return 1.0 if recent > 0 else None

        return round(max(-1.0, min(1.0, (recent - prior) / prior)), 3)

    except Exception as exc:
        logger.warning("Google Trends failed for %r: %s", keyword, exc)
        return None

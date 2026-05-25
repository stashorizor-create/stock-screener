"""
News activity enrichment via yfinance.

Returns two signals:
  - news_count_7d:  number of news articles in the last 7 days (volume proxy)
  - news_sentiment: simple title-based sentiment score (-1 to +1)

No API key required. Works for US and many Nordic tickers.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

POSITIVE_WORDS = {
    "beat", "beats", "record", "surge", "surges", "jumps", "raises", "upgrade",
    "upgrades", "profit", "growth", "strong", "bullish", "buy", "outperform",
    "rally", "rallies", "gains", "rises", "higher", "soars", "wins", "awarded",
    "breakthrough", "launch", "expands", "dividend", "partnership",
}
NEGATIVE_WORDS = {
    "miss", "misses", "cut", "cuts", "falls", "drops", "slumps", "warns",
    "warning", "loss", "losses", "weak", "bearish", "sell", "underperform",
    "decline", "lower", "concerns", "investigation", "lawsuit", "recall",
    "downgrade", "downgrades", "layoffs", "restructuring", "debt",
}


def _score_title(title: str) -> float:
    words = set(title.lower().split())
    pos = len(words & POSITIVE_WORDS)
    neg = len(words & NEGATIVE_WORDS)
    total = pos + neg
    if total == 0:
        return 0.0
    return round((pos - neg) / total, 3)


def get_news_enrichment(symbol: str, lookback_days: int = 7) -> dict:
    """
    Fetch recent news for a ticker and return count + sentiment.

    Returns:
        {
            "news_count_7d":  int,    # articles in lookback window
            "news_sentiment": float,  # -1 to +1
        }
    Both values are None on failure.
    """
    try:
        import yfinance as yf
        news = yf.Ticker(symbol).news or []
    except Exception as exc:
        logger.warning("yfinance news fetch failed for %s: %s", symbol, exc)
        return {"news_count_7d": None, "news_sentiment": None}

    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    recent = []

    for item in news:
        try:
            pub_str = item.get("content", {}).get("pubDate", "")
            if not pub_str:
                continue
            pub = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
            if pub >= cutoff:
                title = item.get("content", {}).get("title", "")
                if title:
                    recent.append(title)
        except Exception:
            continue

    if not recent:
        return {"news_count_7d": 0, "news_sentiment": None, "news_headlines": []}

    sentiment = round(sum(_score_title(t) for t in recent) / len(recent), 3)
    return {
        "news_count_7d":  len(recent),
        "news_sentiment": sentiment,
        "news_headlines": recent[:5],
    }

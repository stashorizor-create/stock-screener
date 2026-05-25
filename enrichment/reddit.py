"""
Reddit mention counter via PRAW.

Requires in .env:
  REDDIT_CLIENT_ID      — from reddit.com/prefs/apps (script app)
  REDDIT_CLIENT_SECRET  — from the same app page

To set up:
  1. Go to https://www.reddit.com/prefs/apps
  2. Click "create another app", choose type = script
  3. Name it anything (e.g. "stock-screener"), redirect URI = http://localhost:8080
  4. Copy the client_id (under the app name) and client_secret into .env
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

_reddit = None


def _get_client():
    global _reddit
    if _reddit is not None:
        return _reddit

    try:
        import praw
        from config.settings import settings

        if not settings.REDDIT_CLIENT_ID or not settings.REDDIT_CLIENT_SECRET:
            logger.info("Reddit credentials not set — mentions unavailable")
            return None

        _reddit = praw.Reddit(
            client_id=settings.REDDIT_CLIENT_ID,
            client_secret=settings.REDDIT_CLIENT_SECRET,
            user_agent=settings.REDDIT_USER_AGENT,
        )
        return _reddit

    except Exception as exc:
        logger.warning("Reddit client init failed: %s", exc)
        return None


def get_mention_counts(
    symbol: str,
    subreddits: list[str] | None = None,
    lookback_hours: int = 24,
    limit_per_sub: int = 100,
) -> dict[str, int | None]:
    """
    Count posts mentioning symbol in each subreddit in the last lookback_hours.

    Args:
        symbol:         Ticker or company name to search for.
        subreddits:     List of subreddit names. Defaults to WSB + Daytrading.
        lookback_hours: How far back to count mentions.
        limit_per_sub:  Max posts to scan per subreddit.

    Returns:
        Dict of {subreddit_name: count} — None values mean fetch failed.
    """
    if subreddits is None:
        subreddits = ["wallstreetbets", "Daytrading"]

    reddit = _get_client()
    if reddit is None:
        return {s: None for s in subreddits}

    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    results: dict[str, int | None] = {}

    for sub_name in subreddits:
        try:
            sub = reddit.subreddit(sub_name)
            count = 0
            for post in sub.search(symbol, sort="new", time_filter="day", limit=limit_per_sub):
                created = datetime.fromtimestamp(post.created_utc, tz=timezone.utc)
                if created >= cutoff:
                    count += 1
            results[sub_name] = count
        except Exception as exc:
            logger.warning("Reddit fetch failed for r/%s %r: %s", sub_name, symbol, exc)
            results[sub_name] = None

    return results

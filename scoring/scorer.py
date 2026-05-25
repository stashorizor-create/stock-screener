"""
Composite scorer — combines all signal components into a 0-100 score.

The technical setup is a GATE: Stage 2 trend must hold and at least one
strategy must fire before this scorer is called.

Component weights (total 100 pts):
  35 pts — Technical quality   (strategy detector scores from runner.py)
  25 pts — Theme alignment     (Claude hot-theme classification)
  15 pts — Relative strength   (RS rank vs screener universe)
  15 pts — Fundamentals        (EPS + revenue growth)
  10 pts — Social signals      (StockTwits + Google Trends + insider + news)
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Individual component scorers
# ---------------------------------------------------------------------------

def score_technical(runner_composite: float) -> float:
    """
    Map the runner's raw composite score (0-100) → 0-35 pts.
    The runner already accounts for strategy quality + multi-strategy bonus.
    """
    return round(min(35.0, runner_composite * 0.35), 2)


def score_relative_strength(rs_rank: float | None) -> float:
    """
    RS rank (percentile vs universe, 0-100) → 0-15 pts.
    Linear scale: rank 100 → 15 pts, rank 0 → 0 pts.
    """
    if rs_rank is None:
        return 0.0
    return round(min(15.0, rs_rank * 0.15), 2)


def score_fundamentals(
    eps_yoy: float | None,
    revenue_yoy: float | None,
    eps_qoq: float | None = None,
) -> float:
    """
    Growth metrics → 0-15 pts.
    Missing data scores 0 for that component — not penalised.
    Hot-theme stocks with weak fundamentals simply score low here, which is
    fine because their theme component carries the score.
    """
    pts = 0.0

    # EPS year-on-year (7 pts)
    if eps_yoy is not None:
        if eps_yoy >= 0.50:   pts += 7.0
        elif eps_yoy >= 0.25: pts += 5.0
        elif eps_yoy >= 0.10: pts += 3.0
        elif eps_yoy > 0:     pts += 1.0

    # Revenue year-on-year (5 pts)
    if revenue_yoy is not None:
        if revenue_yoy >= 0.30:   pts += 5.0
        elif revenue_yoy >= 0.20: pts += 4.0
        elif revenue_yoy >= 0.10: pts += 2.0
        elif revenue_yoy > 0:     pts += 1.0

    # EPS quarter-on-quarter acceleration (3 pts)
    if eps_qoq is not None and eps_qoq > 0:
        pts += 3.0

    return round(min(15.0, pts), 2)


def score_social(
    google_trends_chg: float | None = None,
    insider_buy_days_ago: int | None = None,
    news_sentiment: float | None = None,
    news_count_7d: int | None = None,
    stocktwits_mentions: int | None = None,  # kept for API compat, currently unused
) -> float:
    """
    Social / sentiment signals → 0-10 pts.

    Breakdown:
      3 pts — Google Trends week-over-week acceleration
      3 pts — Insider buy recency
      2 pts — News sentiment (keyword scoring on headlines)
      2 pts — News volume (article count in last 7 days)
    """
    pts = 0.0

    if google_trends_chg is not None:
        if google_trends_chg >= 0.30:   pts += 3.0
        elif google_trends_chg >= 0.10: pts += 2.0
        elif google_trends_chg > 0:     pts += 1.0

    if insider_buy_days_ago is not None:
        if insider_buy_days_ago <= 7:    pts += 3.0
        elif insider_buy_days_ago <= 30: pts += 2.0
        elif insider_buy_days_ago <= 90: pts += 1.0

    if news_sentiment is not None:
        if news_sentiment >= 0.5:   pts += 2.0
        elif news_sentiment >= 0.2: pts += 1.0

    if news_count_7d is not None:
        if news_count_7d >= 8:  pts += 2.0
        elif news_count_7d >= 4: pts += 1.0

    return round(min(10.0, pts), 2)


# ---------------------------------------------------------------------------
# Full composite
# ---------------------------------------------------------------------------

def compute_composite_score(
    runner_score: float,
    theme_score: float = 0.0,
    rs_rank: float | None = None,
    eps_yoy: float | None = None,
    revenue_yoy: float | None = None,
    eps_qoq: float | None = None,
    google_trends_chg: float | None = None,
    insider_buy_days_ago: int | None = None,
    news_sentiment: float | None = None,
    news_count_7d: int | None = None,
    stocktwits_mentions: int | None = None,
) -> dict:
    """
    Compute all components and return a full breakdown dict.

    Args:
        runner_score:  Raw composite from run_all_strategies() (0-100).
        theme_score:   Points from theme classification (0-25).
        rs_rank:       Percentile rank vs universe (0-100).
        eps_yoy:       EPS year-on-year growth as a decimal (e.g. 0.35 = 35%).
        revenue_yoy:   Revenue year-on-year growth as a decimal.
        eps_qoq:       EPS quarter-on-quarter growth as a decimal.
        google_trends_chg: Week-over-week Google Trends change (-1 to 1).
        insider_buy_days_ago: Days since most recent insider buy.
        news_sentiment: News sentiment score (-1 to 1).
        stocktwits_mentions: 24h mention count on StockTwits.

    Returns:
        Dict with composite_score and per-component breakdowns.
    """
    tech  = score_technical(runner_score)
    theme = round(min(25.0, float(theme_score)), 2)
    rs    = score_relative_strength(rs_rank)
    fund  = score_fundamentals(eps_yoy, revenue_yoy, eps_qoq)
    soc   = score_social(google_trends_chg, insider_buy_days_ago, news_sentiment, news_count_7d, stocktwits_mentions)

    total = round(min(100.0, tech + theme + rs + fund + soc), 1)

    return {
        "composite_score":    total,
        "score_technical":    tech,
        "score_theme":        theme,
        "score_rs":           rs,
        "score_fundamentals": fund,
        "score_social":       soc,
    }

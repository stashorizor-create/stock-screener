"""
Loads today's alerts from Supabase for the dashboard.
Falls back to mock data if the DB is unreachable or empty.
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
import sys

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

logger = logging.getLogger(__name__)

TOP_OVERALL  = 20   # signals shown in the main ranked list
TOP_REGIONAL = 5    # signals shown per exchange in the regional breakdown

EXCHANGE_FLAGS = {
    "STO": "🇸🇪",
    "OSL": "🇳🇴",
    "CPH": "🇩🇰",
    "HEL": "🇫🇮",
    "NYSE":   "🇺🇸",
    "NASDAQ": "🇺🇸",
}
EXCHANGE_NAMES = {
    "STO": "Stockholm",
    "OSL": "Oslo",
    "CPH": "Copenhagen",
    "HEL": "Helsinki",
    "NYSE":   "NYSE",
    "NASDAQ": "Nasdaq US",
}


def _alert_to_signal(row) -> dict:
    """Convert a SQLAlchemy Alert + Universe row to the signal dict shape the dashboard expects."""
    alert, universe = row
    strategies_fired = []
    ai_narrative = alert.ai_narrative or ""

    # Parse strategy tags from ai_narrative prefix e.g. "[vcp,qullamaggie] ..."
    if ai_narrative.startswith("["):
        end = ai_narrative.find("]")
        if end != -1:
            tag_str = ai_narrative[1:end]
            strategies_fired = [t.strip() for t in tag_str.split(",") if t.strip()]
            ai_narrative = ai_narrative[end + 1:].strip()

    return {
        "symbol":            alert.symbol,
        "company_name":      universe.name if universe else alert.symbol,
        "exchange":          universe.exchange if universe else "",
        "currency":          universe.currency if universe else "",
        "date":              alert.date.isoformat() if alert.date else "",
        "composite_score":   alert.confidence_score or 0,
        "rs_rank":           None,
        "strategies_fired":  strategies_fired,
        "entry_price":       alert.entry_price,
        "stop_price":        alert.stop_price,
        "target_price":      alert.target_price,
        "risk_reward":       alert.risk_reward,
        "pattern_quality":   alert.pattern_quality,
        "ai_narrative":      ai_narrative,
        "chart_image_path":  alert.chart_image_path,
        # Enrichment — not stored in alerts yet
        "eps_yoy":           None,
        "eps_qoq":           None,
        "revenue_yoy":       None,
        "revenue_qoq":       None,
        "earnings_days_out": None,
        "insider_buy_days_ago": None,
        "news_sentiment":    None,
        "news_count_7d":     None,
        "google_trends_chg": None,
        "theme_name":        None,
        "pattern_notes":     ai_narrative,
    }


def load_signals(run_date: date | None = None) -> tuple[list[dict], str]:
    """
    Load signals from Supabase for the given date (defaults to today).

    Returns:
        (signals, source) where source is "live" or "mock"
        signals are sorted by composite_score descending, capped at TOP_OVERALL
    """
    target_date = run_date or date.today()

    global _last_load_error
    try:
        from config.settings import settings
        if not settings.DATABASE_URL:
            _last_load_error = "DATABASE_URL not set — check .env file"
            return _mock_fallback()

        from database.models import Alert, Universe, SessionLocal

        with SessionLocal() as session:
            rows = (
                session.query(Alert, Universe)
                .outerjoin(Universe, Alert.symbol == Universe.symbol)
                .filter(Alert.date == target_date)
                .order_by(Alert.confidence_score.desc())
                .all()
            )

        if not rows:
            _last_load_error = f"No alerts in DB for {target_date}"
            return _mock_fallback()

        signals = [_alert_to_signal(r) for r in rows]
        logger.info("Loaded %d signals from DB for %s", len(signals), target_date)
        return signals, "live"

    except Exception as exc:
        _last_load_error = str(exc)
        logger.warning("DB load failed (%s) — using mock data", exc)
        return _mock_fallback()


_last_load_error: str = ""


def get_last_load_error() -> str:
    return _last_load_error


def _mock_fallback() -> tuple[list[dict], str]:
    from dashboard.mock_data import MOCK_SIGNALS
    return MOCK_SIGNALS, "mock"


def top_overall(signals: list[dict]) -> list[dict]:
    """Top N signals by composite score."""
    return signals[:TOP_OVERALL]


def top_by_region(signals: list[dict]) -> dict[str, list[dict]]:
    """
    Top N signals per exchange, only including exchanges that have results.
    Returns dict keyed by exchange code, ordered by score within each.
    """
    by_exchange: dict[str, list[dict]] = {}
    for sig in signals:
        ex = sig.get("exchange", "")
        if ex:
            by_exchange.setdefault(ex, []).append(sig)

    return {
        ex: sigs[:TOP_REGIONAL]
        for ex, sigs in by_exchange.items()
        if sigs
    }

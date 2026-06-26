"""
Loads today's alerts from Supabase for the dashboard.
Falls back to mock data if the DB is unreachable or empty.
"""
from __future__ import annotations

import json
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
    "DE":  "🇩🇪",
    "PAR": "🇫🇷",
    "AMS": "🇳🇱",
    "MIL": "🇮🇹",
    "MAD": "🇪🇸",
    "BRU": "🇧🇪",
    "LON": "🇬🇧",
    "CHE": "🇨🇭",
}
EXCHANGE_NAMES = {
    "STO": "Stockholm",
    "OSL": "Oslo",
    "CPH": "Copenhagen",
    "HEL": "Helsinki",
    "NYSE":   "NYSE",
    "NASDAQ": "Nasdaq US",
    "DE":  "Germany",
    "PAR": "Paris",
    "AMS": "Amsterdam",
    "MIL": "Milan",
    "MAD": "Madrid",
    "BRU": "Brussels",
    "LON": "London",
    "CHE": "Switzerland",
}


def _parse_strategies(strategies_json: str | None, ai_narrative: str) -> tuple[list[str], str]:
    """Return (strategies_fired, clean_narrative) from the new JSON column or legacy text prefix."""
    if strategies_json:
        try:
            import json
            strats = json.loads(strategies_json)
            if isinstance(strats, list) and strats:
                # Strip legacy prefix from narrative if present
                narr = ai_narrative or ""
                if narr.startswith("["):
                    end = narr.find("]")
                    if end != -1:
                        narr = narr[end + 1:].strip()
                return strats, narr
        except Exception:
            pass
    # Fall back to legacy text prefix parsing
    narr = ai_narrative or ""
    strats: list[str] = []
    if narr.startswith("["):
        end = narr.find("]")
        if end != -1:
            tag_str = narr[1:end]
            strats = [t.strip() for t in tag_str.split(",") if t.strip()]
            narr = narr[end + 1:].strip()
    return strats, narr


def _alert_to_signal(row) -> dict:
    """Convert a SQLAlchemy Alert + Universe row to the signal dict the dashboard expects."""
    alert, universe = row
    strategies_fired, ai_narrative = _parse_strategies(
        alert.strategies_fired, alert.ai_narrative or ""
    )
    composite = alert.composite_score or alert.confidence_score or 0

    detail = {}
    raw_detail = getattr(alert, "signal_detail", None)
    if raw_detail:
        try:
            detail = json.loads(raw_detail)
        except Exception:
            detail = {}

    return {
        "symbol":            alert.symbol,
        "signals":           detail,
        "company_name":      universe.name if universe else alert.symbol,
        "exchange":          universe.exchange if universe else "",
        "currency":          universe.currency if universe else "",
        "date":              alert.date.isoformat() if alert.date else "",
        "composite_score":   composite,
        "confidence_score":  alert.confidence_score or 0,
        "rs_rank":           alert.rs_rank,
        "strategies_fired":  strategies_fired,
        "entry_price":       alert.entry_price,
        "stop_price":        alert.stop_price,
        "target_price":      alert.target_price,
        "risk_reward":       alert.risk_reward,
        "pattern_quality":   alert.pattern_quality,
        "ai_narrative":      ai_narrative,
        "chart_image_path":  alert.chart_image_path,
        "eps_yoy":           alert.eps_yoy,
        "eps_qoq":           alert.eps_qoq,
        "revenue_yoy":       alert.revenue_yoy,
        "revenue_qoq":       alert.revenue_qoq,
        "earnings_days_out": alert.earnings_days_out,
        "insider_buy_days_ago": None,
        "news_sentiment":    None,
        "news_count_7d":     None,
        "google_trends_chg": None,
        "theme_name":        alert.theme_name or None,
        "theme_momentum":    alert.theme_momentum or None,
        "theme_narrative":   alert.theme_narrative or None,
        "fit_strength":      alert.fit_strength or None,
        "theme_score":       alert.theme_score or 0,
        "pattern_notes":     alert.pattern_notes or ai_narrative,
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

    # --- Try Supabase REST API first (works on Streamlit Cloud) ---
    try:
        import streamlit as st
        supa_url = st.secrets.get("SUPABASE_URL", "")
        supa_key = st.secrets.get("SUPABASE_KEY", "")
        if supa_url and supa_key:
            return _load_via_supabase(supa_url, supa_key, target_date)
    except Exception:
        pass  # not running in Streamlit context, fall through to SQLAlchemy

    # --- Fall back to direct SQLAlchemy (local dev) ---
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


def _load_via_supabase(url: str, key: str, target_date) -> tuple[list[dict], str]:
    """Load alerts via Supabase REST API (HTTPS — works on Streamlit Cloud)."""
    global _last_load_error
    try:
        from supabase import create_client
        client = create_client(url, key)

        resp = (
            client.table("alerts")
            .select("*, universe(name, exchange, currency)")
            .eq("date", str(target_date))
            .order("confidence_score", desc=True)
            .execute()
        )

        rows = resp.data or []
        if not rows:
            _last_load_error = f"No alerts in DB for {target_date}"
            return _mock_fallback()

        signals = [_supabase_row_to_signal(r) for r in rows]
        logger.info("Loaded %d signals via Supabase REST for %s", len(signals), target_date)
        return signals, "live"

    except Exception as exc:
        _last_load_error = str(exc)
        logger.warning("Supabase REST failed (%s) — using mock data", exc)
        return _mock_fallback()


def _supabase_row_to_signal(row: dict) -> dict:
    """Convert a Supabase REST API row to the signal dict the dashboard expects."""
    universe = row.get("universe") or {}
    strategies_fired, ai_narrative = _parse_strategies(
        row.get("strategies_fired"), row.get("ai_narrative") or ""
    )
    composite = row.get("composite_score") or row.get("confidence_score") or 0

    detail = row.get("signal_detail")
    if isinstance(detail, str):
        try:
            detail = json.loads(detail)
        except Exception:
            detail = {}
    elif not isinstance(detail, dict):
        detail = {}

    return {
        "symbol":            row.get("symbol", ""),
        "signals":           detail,
        "company_name":      universe.get("name") or row.get("symbol", ""),
        "exchange":          universe.get("exchange") or "",
        "currency":          universe.get("currency") or "",
        "date":              row.get("date") or "",
        "composite_score":   composite,
        "confidence_score":  row.get("confidence_score") or 0,
        "rs_rank":           row.get("rs_rank"),
        "strategies_fired":  strategies_fired,
        "entry_price":       row.get("entry_price"),
        "stop_price":        row.get("stop_price"),
        "target_price":      row.get("target_price"),
        "risk_reward":       row.get("risk_reward"),
        "pattern_quality":   row.get("pattern_quality"),
        "ai_narrative":      ai_narrative,
        "chart_image_path":  row.get("chart_image_path"),
        "eps_yoy":           row.get("eps_yoy"),
        "eps_qoq":           row.get("eps_qoq"),
        "revenue_yoy":       row.get("revenue_yoy"),
        "revenue_qoq":       row.get("revenue_qoq"),
        "earnings_days_out": row.get("earnings_days_out"),
        "insider_buy_days_ago": None,
        "news_sentiment":    None,
        "news_count_7d":     None,
        "google_trends_chg": None,
        "theme_name":        row.get("theme_name") or None,
        "theme_momentum":    row.get("theme_momentum") or None,
        "theme_narrative":   row.get("theme_narrative") or None,
        "fit_strength":      row.get("fit_strength") or None,
        "theme_score":       row.get("theme_score") or 0,
        "pattern_notes":     row.get("pattern_notes") or ai_narrative,
    }


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

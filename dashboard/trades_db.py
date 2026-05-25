"""
Trade journal — CRUD against the 'trades' Supabase table.
Uses the anon key from st.secrets (cloud) or SERVICE_KEY from .env (local).
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


def _client():
    try:
        import streamlit as st
        url = st.secrets.get("SUPABASE_URL", "")
        key = st.secrets.get("SUPABASE_KEY", "")
        if url and key:
            from supabase import create_client
            return create_client(url, key)
    except Exception:
        pass
    try:
        from config.settings import settings
        if settings.SUPABASE_URL and settings.SUPABASE_SERVICE_KEY:
            from supabase import create_client
            return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Write operations
# ---------------------------------------------------------------------------

def log_entry(
    symbol: str,
    strategy: str,
    entry_price: float,
    stop_price: float,
    target_price: Optional[float],
    alert_date: str,
    notes: str = "",
) -> bool:
    """Insert a new open trade. Returns True on success."""
    c = _client()
    if c is None:
        return False
    try:
        c.table("trades").insert({
            "symbol":       symbol,
            "strategy":     strategy,
            "alert_date":   alert_date or None,
            "entry_date":   date.today().isoformat(),
            "entry_price":  entry_price,
            "stop_price":   stop_price,
            "target_price": target_price if target_price and target_price > 0 else None,
            "outcome":      "open",
            "notes":        notes or None,
            "created_at":   datetime.now(timezone.utc).isoformat(),
        }).execute()
        return True
    except Exception as exc:
        logger.warning("log_entry failed: %s", exc)
        return False


def record_exit(trade_id: int, exit_price: float, notes: str = "") -> bool:
    """Close a trade, calculate realized R:R and outcome. Returns True on success."""
    c = _client()
    if c is None:
        return False
    try:
        resp = c.table("trades").select("*").eq("id", trade_id).single().execute()
        t = resp.data
        if not t:
            return False

        entry = t.get("entry_price") or 0.0
        stop  = t.get("stop_price")  or 0.0
        risk  = entry - stop

        realized_rr = round((exit_price - entry) / risk, 2) if risk > 0 else None

        if realized_rr is None:
            outcome = "breakeven"
        elif realized_rr >= 0.1:
            outcome = "win"
        elif realized_rr <= -0.9:
            outcome = "loss"
        else:
            outcome = "breakeven"

        existing_notes = t.get("notes") or ""
        combined = f"{existing_notes} | Exit: {notes}".strip(" |") if notes else existing_notes

        c.table("trades").update({
            "exit_date":   date.today().isoformat(),
            "exit_price":  exit_price,
            "realized_rr": realized_rr,
            "outcome":     outcome,
            "notes":       combined or None,
        }).eq("id", trade_id).execute()
        return True
    except Exception as exc:
        logger.warning("record_exit failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Read operations
# ---------------------------------------------------------------------------

def get_open_trades() -> list[dict]:
    c = _client()
    if c is None:
        return []
    try:
        return c.table("trades").select("*").eq("outcome", "open") \
                .order("entry_date", desc=True).execute().data or []
    except Exception:
        return []


def get_closed_trades(limit: int = 100) -> list[dict]:
    c = _client()
    if c is None:
        return []
    try:
        return c.table("trades").select("*").neq("outcome", "open") \
                .order("exit_date", desc=True).limit(limit).execute().data or []
    except Exception:
        return []


def get_strategy_stats() -> list[dict]:
    """Aggregate win rate and avg realized R:R per strategy from all closed trades."""
    closed = get_closed_trades(limit=500)
    if not closed:
        return []

    agg: dict[str, dict] = defaultdict(lambda: {"trades": 0, "wins": 0, "rr_sum": 0.0, "rr_n": 0})
    for t in closed:
        s = t.get("strategy") or "unknown"
        agg[s]["trades"] += 1
        if t.get("outcome") == "win":
            agg[s]["wins"] += 1
        rr = t.get("realized_rr")
        if rr is not None:
            agg[s]["rr_sum"] += rr
            agg[s]["rr_n"]   += 1

    result = []
    for strat, a in sorted(agg.items(), key=lambda x: -x[1]["trades"]):
        result.append({
            "strategy": strat,
            "trades":   a["trades"],
            "wins":     a["wins"],
            "win_rate": a["wins"] / a["trades"] if a["trades"] else 0.0,
            "avg_rr":   round(a["rr_sum"] / a["rr_n"], 2) if a["rr_n"] else None,
        })
    return result

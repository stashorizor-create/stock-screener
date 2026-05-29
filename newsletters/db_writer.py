"""Write extracted newsletter data to Supabase via the supabase-py client."""
from __future__ import annotations

import logging
from datetime import date, datetime

logger = logging.getLogger(__name__)


def _get_client():
    """Get Supabase client — same key lookup order as _supa_client() in app.py."""
    url = key = ""
    try:
        import streamlit as st
        url = st.secrets.get("SUPABASE_URL", "")
        key = (st.secrets.get("SUPABASE_KEY") or
               st.secrets.get("SUPABASE_SERVICE_KEY") or "")
    except Exception:
        pass
    if not url or not key:
        import os
        from config.settings import settings
        url = url or settings.SUPABASE_URL
        key = key or settings.SUPABASE_SERVICE_KEY
    if not url or not key:
        raise RuntimeError("SUPABASE_URL or SUPABASE_KEY not configured in Streamlit secrets")
    from supabase import create_client
    return create_client(url, key)


def write_newsletter(
    email_date: date,
    subject: str,
    extracted: dict,
    vision_trades: list[dict],
    raw_text: str,
    dry_run: bool = False,
) -> None:
    """Upsert one newsletter into newsletter_market + newsletter_picks."""

    stance = (extracted.get("market_stance") or "unknown").lower()
    notes  = extracted.get("market_notes") or ""

    picks: list[dict] = []

    for item in extracted.get("focus_list") or []:
        ticker = _clean_ticker(item.get("ticker"))
        if ticker:
            picks.append({
                "email_date":     str(email_date),
                "ticker":         ticker,
                "action":         "FOCUS",
                "entry_price":    _f(item.get("price_level")),
                "notes":          item.get("notes"),
                "source_section": "focus_list",
            })

    for item in extracted.get("portfolio_moves") or []:
        ticker = _clean_ticker(item.get("ticker"))
        if ticker:
            picks.append({
                "email_date":     str(email_date),
                "ticker":         ticker,
                "action":         (item.get("action") or "WATCH").upper(),
                "notes":          item.get("notes"),
                "source_section": "portfolio",
            })

    for raw in extracted.get("scan_21dma") or []:
        ticker = _clean_ticker(raw)
        if ticker:
            picks.append({"email_date": str(email_date), "ticker": ticker,
                          "action": "WATCH", "source_section": "scan_21dma"})

    for raw in extracted.get("ep_list") or []:
        ticker = _clean_ticker(raw)
        if ticker:
            picks.append({"email_date": str(email_date), "ticker": ticker,
                          "action": "EP", "source_section": "ep_list"})

    for raw in extracted.get("stalk_list") or []:
        ticker = _clean_ticker(raw)
        if ticker:
            picks.append({"email_date": str(email_date), "ticker": ticker,
                          "action": "STALK", "source_section": "stalklist"})

    # Portfolio table from text extraction (used when vision finds nothing)
    # Vision trades take precedence — collected below will overwrite via upsert
    _vision_tickers = {_clean_ticker(t.get("ticker")) for t in vision_trades if t.get("entry")}
    for trade in extracted.get("portfolio_table") or []:
        ticker = _clean_ticker(trade.get("ticker"))
        if ticker and trade.get("entry") is not None and ticker not in _vision_tickers:
            picks.append({
                "email_date":        str(email_date),
                "ticker":            ticker,
                "action":            (trade.get("action") or "LONG").upper(),
                "entry_price":       _f(trade.get("entry")),
                "stop_price":        _f(trade.get("stop")),
                "target_price":      _f(trade.get("trim_1")),
                "trim_2":            _f(trade.get("trim_2")),
                "trim_3":            _f(trade.get("trim_3")),
                "position_size_pct": _f(trade.get("size_pct")),
                "notes":             trade.get("notes"),
                "source_section":    "portfolio_table",
            })

    for trade in vision_trades:
        ticker = _clean_ticker(trade.get("ticker"))
        if ticker and trade.get("entry") is not None:
            picks.append({
                "email_date":        str(email_date),
                "ticker":            ticker,
                "action":            (trade.get("action") or "LONG").upper(),
                "entry_price":       _f(trade.get("entry")),
                "stop_price":        _f(trade.get("stop")),
                "target_price":      _f(trade.get("trim_1")),
                "trim_2":            _f(trade.get("trim_2")),
                "trim_3":            _f(trade.get("trim_3")),
                "position_size_pct": _f(trade.get("size_pct")),
                "notes":             trade.get("notes"),
                "source_section":    "portfolio_table",
            })

    if dry_run:
        print(f"[DRY RUN] {email_date} | stance={stance} | picks={len(picks)}")
        for p in picks:
            print(f"  [{p['source_section']}] {p['ticker']} {p.get('action','')}"
                  + (f"  entry={p.get('entry_price')} stop={p.get('stop_price')}"
                     f"  trim1={p.get('target_price')} trim2={p.get('trim_2')} trim3={p.get('trim_3')}"
                     if p.get('entry_price') else ""))
        return

    client = _get_client()

    # Upsert newsletter_market row
    client.table("newsletter_market").upsert({
        "email_date":     str(email_date),
        "subject":        subject,
        "market_stance":  stance,
        "market_notes":   notes,
        "raw_text":       raw_text[:10000],
        "processed_at":   datetime.utcnow().isoformat(),
    }, on_conflict="email_date").execute()

    if not picks:
        logger.info("Wrote newsletter %s: no picks", email_date)
        return

    # Split into portfolio_table (full upsert) vs others (ignore duplicates)
    portfolio_picks = [p for p in picks if p["source_section"] == "portfolio_table"]
    other_picks     = [p for p in picks if p["source_section"] != "portfolio_table"]

    if portfolio_picks:
        client.table("newsletter_picks").upsert(
            portfolio_picks,
            on_conflict="email_date,ticker,action,source_section",
        ).execute()

    if other_picks:
        client.table("newsletter_picks").upsert(
            other_picks,
            on_conflict="email_date,ticker,action,source_section",
            ignore_duplicates=True,
        ).execute()

    logger.info("Wrote newsletter %s: %d picks", email_date, len(picks))


def _clean_ticker(raw) -> str | None:
    if not raw:
        return None
    return str(raw).lstrip("$").upper().strip() or None


def _f(v) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None

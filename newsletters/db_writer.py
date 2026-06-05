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
    replace_portfolio: bool = False,
) -> None:
    """Upsert one newsletter into newsletter_market + newsletter_picks.

    replace_portfolio: if True, delete this date's existing portfolio_table rows
    before writing — full-replace semantics so a re-uploaded screenshot reflects
    the current positions exactly (old/closed positions disappear instead of
    piling up). Used by the manual screenshot upload.
    """

    stance       = (extracted.get("market_stance") or "unknown").lower()
    notes        = extracted.get("market_notes") or ""
    risk_env     = (extracted.get("risk_environment") or "neutral").lower()
    risk_rat     = extracted.get("risk_rationale") or ""

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

    # "TOP SETUPS @ 21dma-structure area" — ranked names; Alex's score kept in notes.
    for item in extracted.get("top_setups") or []:
        if isinstance(item, dict):
            ticker = _clean_ticker(item.get("ticker"))
            score  = item.get("score")
        else:
            ticker, score = _clean_ticker(item), None
        if ticker:
            picks.append({"email_date": str(email_date), "ticker": ticker,
                          "action": "WATCH", "source_section": "top_setups",
                          "notes": (f"Alex {score}" if score is not None else None)})

    # "THEMES SETTING UP" — grouped by theme; theme name stored in notes for display.
    for grp in extracted.get("themes_setting_up") or []:
        if not isinstance(grp, dict):
            continue
        theme = (grp.get("theme") or "").strip()
        for raw in grp.get("tickers") or []:
            ticker = _clean_ticker(raw)
            if ticker:
                picks.append({"email_date": str(email_date), "ticker": ticker,
                              "action": "WATCH", "source_section": "themes_setup",
                              "notes": theme or None})

    # "Liquid Leaders 21dma-structure Pullback scan (LONG)"
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
                "entry_date":        _date_str(trade.get("entry_date")),
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
                "entry_date":        _date_str(trade.get("entry_date")),
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
        "email_date":       str(email_date),
        "subject":          subject,
        "market_stance":    stance,
        "market_notes":     notes,
        "risk_environment": risk_env,
        "risk_rationale":   risk_rat,
        "raw_text":         raw_text[:10000],
        "processed_at":     datetime.utcnow().isoformat(),
    }, on_conflict="email_date").execute()

    # Full-replace the portfolio snapshot for this date (manual re-upload): clear
    # old portfolio_table rows first so removed/closed positions don't linger.
    # Only touches portfolio_table — focus/scan/ep/stalk rows are left intact.
    if replace_portfolio:
        client.table("newsletter_picks") \
            .delete() \
            .eq("email_date", str(email_date)) \
            .eq("source_section", "portfolio_table") \
            .execute()

    if not picks:
        logger.info("Wrote newsletter %s: no picks", email_date)
        return

    # Split into portfolio_table (full upsert) vs others (ignore duplicates)
    portfolio_picks = [p for p in picks if p["source_section"] == "portfolio_table"]
    other_picks     = [p for p in picks if p["source_section"] != "portfolio_table"]

    if portfolio_picks:
        # entry_price is part of the conflict key: Alex can hold several
        # positions in the same ticker (scaled in on different dates/prices), so
        # they are distinct rows and must NOT be collapsed. We still dedupe by
        # the *full* key — including entry_price — because a single batch upsert
        # cannot touch the same conflict key twice (Postgres: "ON CONFLICT DO
        # UPDATE command cannot affect row a second time"); only genuinely
        # identical rows (same entry) collapse, last wins.
        portfolio_picks = _dedupe_by_conflict_key(portfolio_picks)
        client.table("newsletter_picks").upsert(
            portfolio_picks,
            on_conflict="email_date,ticker,action,source_section,entry_price,entry_date",
        ).execute()

    if other_picks:
        client.table("newsletter_picks").upsert(
            other_picks,
            on_conflict="email_date,ticker,action,source_section,entry_price,entry_date",
            ignore_duplicates=True,
        ).execute()

    logger.info("Wrote newsletter %s: %d picks", email_date, len(picks))


def _dedupe_by_conflict_key(rows: list[dict]) -> list[dict]:
    """Keep one row per (email_date, ticker, action, source_section, entry_price, entry_date); last wins.

    entry_price and entry_date are in the key so distinct positions in the same ticker
    (scaled in on different dates/prices) are preserved — only exact duplicates of the
    same position collapse.
    """
    by_key: dict[tuple, dict] = {}
    for r in rows:
        key = (r.get("email_date"), r.get("ticker"), r.get("action"),
               r.get("source_section"), r.get("entry_price"), r.get("entry_date"))
        by_key[key] = r
    return list(by_key.values())


def _clean_ticker(raw) -> str | None:
    if not raw:
        return None
    return str(raw).lstrip("$").upper().strip() or None


def _f(v) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _date_str(v) -> str | None:
    """Accept only a real YYYY-MM-DD date; reject anything the model couldn't read.

    Guards the DATE column against hallucinated/garbage values — a bad date is
    dropped to null rather than stored as a fantasy entry date.
    """
    if not v:
        return None
    s = str(v).strip()[:10]
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return s
    except ValueError:
        return None

"""Write extracted newsletter data to Supabase via psycopg2 (avoids SQLAlchemy import-time URL issue)."""
from __future__ import annotations

import logging
from datetime import date, datetime

logger = logging.getLogger(__name__)


def _get_conn():
    """Return a psycopg2 connection, reading DATABASE_URL at call time."""
    import os
    from config.settings import _load_streamlit_secrets
    _load_streamlit_secrets()
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    url = url.replace("postgresql://", "postgres://", 1)  # psycopg2 uses postgres://
    import psycopg2
    return psycopg2.connect(url)


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
                "email_date":     email_date,
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
                "email_date":     email_date,
                "ticker":         ticker,
                "action":         (item.get("action") or "WATCH").upper(),
                "notes":          item.get("notes"),
                "source_section": "portfolio",
            })

    for raw in extracted.get("scan_21dma") or []:
        ticker = _clean_ticker(raw)
        if ticker:
            picks.append({"email_date": email_date, "ticker": ticker,
                          "action": "WATCH", "source_section": "scan_21dma"})

    for raw in extracted.get("ep_list") or []:
        ticker = _clean_ticker(raw)
        if ticker:
            picks.append({"email_date": email_date, "ticker": ticker,
                          "action": "EP", "source_section": "ep_list"})

    for raw in extracted.get("stalk_list") or []:
        ticker = _clean_ticker(raw)
        if ticker:
            picks.append({"email_date": email_date, "ticker": ticker,
                          "action": "STALK", "source_section": "stalklist"})

    for trade in vision_trades:
        ticker = _clean_ticker(trade.get("ticker"))
        if ticker and trade.get("entry") is not None:
            picks.append({
                "email_date":        email_date,
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
                     f"  size={p.get('position_size_pct')}%"
                     f"  trim1={p.get('target_price')} trim2={p.get('trim_2')} trim3={p.get('trim_3')}"
                     if p.get('entry_price') else ""))
        return

    conn = _get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                # Upsert newsletter_market
                cur.execute("""
                    INSERT INTO newsletter_market
                        (email_date, subject, market_stance, market_notes, raw_text, processed_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (email_date) DO UPDATE SET
                        market_stance = EXCLUDED.market_stance,
                        market_notes  = EXCLUDED.market_notes,
                        processed_at  = EXCLUDED.processed_at
                """, (email_date, subject, stance, notes, raw_text[:10000], datetime.utcnow()))

                # Upsert newsletter_picks
                for p in picks:
                    if p.get("source_section") == "portfolio_table":
                        cur.execute("""
                            INSERT INTO newsletter_picks
                                (email_date, ticker, action, entry_price, stop_price,
                                 target_price, trim_2, trim_3, position_size_pct, notes, source_section)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                            ON CONFLICT (email_date, ticker, action, source_section) DO UPDATE SET
                                entry_price       = EXCLUDED.entry_price,
                                stop_price        = EXCLUDED.stop_price,
                                target_price      = EXCLUDED.target_price,
                                trim_2            = EXCLUDED.trim_2,
                                trim_3            = EXCLUDED.trim_3,
                                position_size_pct = EXCLUDED.position_size_pct,
                                notes             = EXCLUDED.notes
                        """, (
                            p["email_date"], p["ticker"], p.get("action"),
                            p.get("entry_price"), p.get("stop_price"),
                            p.get("target_price"), p.get("trim_2"), p.get("trim_3"),
                            p.get("position_size_pct"), p.get("notes"), p["source_section"],
                        ))
                    else:
                        cur.execute("""
                            INSERT INTO newsletter_picks
                                (email_date, ticker, action, entry_price, notes, source_section)
                            VALUES (%s,%s,%s,%s,%s,%s)
                            ON CONFLICT (email_date, ticker, action, source_section) DO NOTHING
                        """, (
                            p["email_date"], p["ticker"], p.get("action"),
                            p.get("entry_price"), p.get("notes"), p["source_section"],
                        ))
    finally:
        conn.close()

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

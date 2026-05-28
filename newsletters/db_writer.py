"""Write extracted newsletter data to Supabase (newsletter_market + newsletter_picks tables)."""
from __future__ import annotations

import logging
from datetime import date, datetime

from sqlalchemy.dialects.postgresql import insert as pg_insert

from database.models import SessionLocal, NewsletterMarket, NewsletterPick

logger = logging.getLogger(__name__)


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
                "email_date":    email_date,
                "ticker":        ticker,
                "action":        "FOCUS",
                "entry_price":   _f(item.get("price_level")),
                "notes":         item.get("notes"),
                "source_section": "focus_list",
            })

    for item in extracted.get("portfolio_moves") or []:
        ticker = _clean_ticker(item.get("ticker"))
        if ticker:
            picks.append({
                "email_date":    email_date,
                "ticker":        ticker,
                "action":        (item.get("action") or "WATCH").upper(),
                "notes":         item.get("notes"),
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
        # Require at least entry price to be present (Alex's table has entry but not always stop/target)
        if ticker and trade.get("entry") is not None:
            picks.append({
                "email_date":       email_date,
                "ticker":           ticker,
                "action":           (trade.get("action") or "LONG").upper(),
                "entry_price":      _f(trade.get("entry")),
                "stop_price":       _f(trade.get("stop")),
                "target_price":     _f(trade.get("target")),
                "position_size_pct": _f(trade.get("size_pct")),
                "notes":            trade.get("notes"),
                "source_section":   "portfolio_table",
            })

    if dry_run:
        print(f"[DRY RUN] {email_date} | stance={stance} | picks={len(picks)}")
        for p in picks:
            print(f"  [{p['source_section']}] {p['ticker']} {p['action']}"
                  + (f"  entry={p.get('entry_price')} stop={p.get('stop_price')}"
                     if p.get('entry_price') else ""))
        return

    with SessionLocal() as session:
        stmt = pg_insert(NewsletterMarket).values(
            email_date=email_date,
            subject=subject,
            market_stance=stance,
            market_notes=notes,
            raw_text=raw_text[:10000],
            processed_at=datetime.utcnow(),
        ).on_conflict_do_update(
            index_elements=["email_date"],
            set_={
                "market_stance": stance,
                "market_notes":  notes,
                "processed_at":  datetime.utcnow(),
            },
        )
        session.execute(stmt)

        for pick in picks:
            session.execute(pg_insert(NewsletterPick).values(**pick).on_conflict_do_nothing())

        session.commit()

    logger.info("Wrote newsletter %s: %d picks", email_date, len(picks))


# ---------------------------------------------------------------------------

def _clean_ticker(raw) -> str | None:
    if not raw:
        return None
    return str(raw).lstrip("$").upper().strip() or None


def _f(v) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None

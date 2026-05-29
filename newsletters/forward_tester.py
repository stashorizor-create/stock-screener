"""Compute forward-test metrics for portfolio_table picks via Borsdata OHLCV API."""
from __future__ import annotations

import logging
from datetime import date

logger = logging.getLogger(__name__)


def run_forward_tests(dry_run: bool = False) -> int:
    """
    For every portfolio_table pick with an entry price, compute performance metrics
    using Borsdata OHLCV data fetched live.  Upserts into newsletter_forward_tests.
    Returns number of picks successfully processed.
    """
    import pandas as pd
    from sqlalchemy import select
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from data.ingestor import BorsdataClient
    from database.models import SessionLocal, NewsletterPick, NewsletterForwardTest

    today = date.today()

    with SessionLocal() as session:
        picks = session.execute(
            select(NewsletterPick)
            .where(NewsletterPick.source_section == "portfolio_table")
            .where(NewsletterPick.entry_price.isnot(None))
            .order_by(NewsletterPick.email_date, NewsletterPick.ticker)
        ).scalars().all()

        if not picks:
            logger.info("No portfolio picks found")
            return 0

        # Unique ticker → earliest entry date (fetch OHLCV once per ticker)
        ticker_earliest: dict[str, date] = {}
        for p in picks:
            if p.ticker not in ticker_earliest or p.email_date < ticker_earliest[p.ticker]:
                ticker_earliest[p.ticker] = p.email_date

        logger.info("Loading Borsdata global instruments...")
        client = BorsdataClient()
        df_global = client.get_instruments_global()

        # Filter to US markets to avoid ticker collisions (e.g. ARM = Arm Holdings, not Arima RE)
        _US_MARKET_IDS = {29, 32, 33, 34}
        sym_to_id: dict[str, int] = {}
        if not df_global.empty:
            df_us = df_global[df_global["marketId"].isin(_US_MARKET_IDS)]
            for _, row in df_us.iterrows():
                sym = str(row.get("ticker") or "").upper().strip()
                if sym:
                    sym_to_id[sym] = int(row["insId"])

        # Fetch OHLCV per ticker
        logger.info("Fetching OHLCV for %d unique tickers...", len(ticker_earliest))
        ohlcv_cache: dict[str, pd.DataFrame] = {}
        for ticker, earliest in ticker_earliest.items():
            bid = sym_to_id.get(ticker)
            if not bid:
                logger.debug("No Borsdata ID for %s", ticker)
                continue
            try:
                df = client.get_ohlcv(bid, from_date=earliest, to_date=today, max_count=500)
                if not df.empty:
                    ohlcv_cache[ticker] = df
                    logger.debug("OHLCV %s: %d rows", ticker, len(df))
            except Exception as exc:
                logger.warning("OHLCV fetch failed for %s: %s", ticker, exc)

        # Compute metrics per pick
        count = 0
        for pick in picks:
            df_full = ohlcv_cache.get(pick.ticker)
            if df_full is None or df_full.empty:
                logger.warning("No OHLCV for %s — skipping", pick.ticker)
                continue

            df = df_full[df_full["date"] >= pick.email_date].copy()
            if df.empty:
                logger.warning("No OHLCV for %s from %s", pick.ticker, pick.email_date)
                continue

            entry = pick.entry_price
            stop  = pick.stop_price

            max_high   = float(df["high"].max())
            min_low    = float(df["low"].min())
            last_close = float(df["close"].iloc[-1])
            last_date  = df["date"].iloc[-1]
            days_held  = (last_date - pick.email_date).days

            max_mfe_pct        = (max_high   - entry) / entry * 100
            max_mae_pct        = (min_low    - entry) / entry * 100
            current_return_pct = (last_close - entry) / entry * 100

            stop_hit      = False
            stop_hit_date = None
            if stop is not None:
                hit_rows = df[df["low"] <= stop]
                if not hit_rows.empty:
                    stop_hit      = True
                    stop_hit_date = hit_rows["date"].iloc[0]

            r_multiple = None
            if stop is not None and entry != stop:
                r_multiple = (last_close - entry) / (entry - stop)

            status = "stopped" if stop_hit else "active"

            metrics = {
                "pick_id":             pick.id,
                "email_date":          pick.email_date,
                "ticker":              pick.ticker,
                "action":              pick.action,
                "entry_price":         entry,
                "stop_price":          stop,
                "trim_1":              pick.target_price,
                "trim_2":              getattr(pick, "trim_2", None),
                "trim_3":              getattr(pick, "trim_3", None),
                "size_pct":            pick.position_size_pct,
                "evaluated_at":        today,
                "days_held":           days_held,
                "current_price":       last_close,
                "current_return_pct":  current_return_pct,
                "max_high":            max_high,
                "max_mfe_pct":         max_mfe_pct,
                "min_low":             min_low,
                "max_mae_pct":         max_mae_pct,
                "stop_hit":            stop_hit,
                "stop_hit_date":       stop_hit_date,
                "r_multiple":          r_multiple,
                "status":              status,
            }

            if dry_run:
                r_str   = f"{r_multiple:+.2f}R" if r_multiple is not None else "N/A"
                ret_str = f"{current_return_pct:+.1f}%"
                print(f"  [{pick.email_date}] {pick.ticker:8s}  entry={entry:.2f}"
                      f"  current={last_close:.2f}  ret={ret_str}  R={r_str}"
                      f"  {'STOPPED' if stop_hit else 'active':7s}  days={days_held}")
                count += 1
                continue

            update_cols = {k: v for k, v in metrics.items() if k != "pick_id"}
            session.execute(
                pg_insert(NewsletterForwardTest).values(**metrics)
                .on_conflict_do_update(index_elements=["pick_id"], set_=update_cols)
            )
            count += 1

        if not dry_run:
            session.commit()

    logger.info("Forward test: processed %d picks", count)
    return count

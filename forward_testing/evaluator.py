"""
Forward test writer and evaluator.

Write: called each nightly run — stores one ForwardTest row per signal/strategy.
Evaluate: called each nightly run — closes out tests whose check_date has passed.

Stop logic (configurable via stop_price column):
  Default initial stop = entry_candle_low (low of the entry day candle).
  You can UPDATE stop_price in Supabase at any time to change the rule for a specific row.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

import pandas as pd

logger = logging.getLogger(__name__)


FORWARD_TEST_MIN_SCORE = 50.0  # signals below this score are not worth tracking


def write_forward_tests(
    raw_signals: list[dict],
    run_date: date,
    dry_run: bool = False,
) -> None:
    """Insert a ForwardTest row per signal/strategy for signals scoring >= FORWARD_TEST_MIN_SCORE."""
    eligible = [s for s in raw_signals if (s.get("composite_score") or 0) >= FORWARD_TEST_MIN_SCORE]
    if dry_run:
        logger.info("Forward tests: dry-run, skipping write (%d/%d signals above score %.0f)",
                    len(eligible), len(raw_signals), FORWARD_TEST_MIN_SCORE)
        return

    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from database.models import ForwardTest, SessionLocal

    check_date = run_date + timedelta(days=60)
    rows_written = 0

    def _f(v):
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    with SessionLocal() as session:
        for sig in eligible:
            strategies = sig.get("strategies_fired") or ["unknown"]
            for strategy in strategies:
                initial_stop = _f(sig.get("entry_candle_low") or sig.get("stop_price"))
                stmt = (
                    pg_insert(ForwardTest)
                    .values(
                        symbol=sig["symbol"],
                        exchange=sig.get("exchange", ""),
                        currency=sig.get("currency", ""),
                        strategy=strategy,
                        composite_score=_f(sig.get("composite_score")),
                        entry_date=run_date,
                        entry_price=_f(sig.get("entry_price")),
                        entry_candle_low=_f(sig.get("entry_candle_low")),
                        stop_price=initial_stop,
                        pivot_price=_f(sig.get("pivot_price") or sig.get("entry_price")),
                        check_date=check_date,
                        status="pending",
                    )
                    .on_conflict_do_nothing()
                )
                session.execute(stmt)
                rows_written += 1
        session.commit()

    logger.info("Forward tests written: %d rows for %s (check date %s, %d signals below score cutoff skipped)",
                rows_written, run_date, check_date, len(raw_signals) - len(eligible))


def _build_insid_resolver(borsdata_client) -> tuple[dict, dict]:
    """Build symbol→Borsdata insId lookups from the instrument lists.

    universe.borsdata_id is not populated (the nightly upsert omits it), so the
    evaluator resolves ids itself. Returns two maps:
      by_exch_ticker: {(exchange_code, TICKER): insId}  — exact, disambiguated
      by_ticker:      {TICKER: [insId, ...]}            — fallback when ticker is unique
    """
    from config.universe_config import MARKET_ID_TO_EXCHANGE

    frames = []
    for fetch in (borsdata_client.get_instruments, borsdata_client.get_instruments_global):
        try:
            frames.append(fetch())
        except Exception as exc:
            logger.warning("Resolver: %s failed: %s", getattr(fetch, "__name__", "fetch"), exc)

    by_exch_ticker: dict[tuple[str, str], int] = {}
    by_ticker: dict[str, list[int]] = {}
    for df in frames:
        if df is None or df.empty:
            continue
        for ins_id, ticker, market_id in zip(df["insId"], df.get("ticker", []), df["marketId"]):
            try:
                ins_id = int(ins_id)
                market_id = int(market_id)
            except (TypeError, ValueError):
                continue
            ticker = str(ticker or "").upper().strip()
            if not ticker:
                continue
            exch = MARKET_ID_TO_EXCHANGE.get(market_id)
            if exch:
                by_exch_ticker[(exch, ticker)] = ins_id
            by_ticker.setdefault(ticker, [])
            if ins_id not in by_ticker[ticker]:
                by_ticker[ticker].append(ins_id)
    return by_exch_ticker, by_ticker


def _resolve_insid(ft, by_exch_ticker: dict, by_ticker: dict) -> int | None:
    """Resolve a ForwardTest row to a Borsdata insId, disambiguating by exchange."""
    ticker = str(ft.symbol or "").upper().strip()
    exch = str(ft.exchange or "").upper().strip()
    if (exch, ticker) in by_exch_ticker:
        return by_exch_ticker[(exch, ticker)]
    ids = by_ticker.get(ticker, [])
    if len(ids) == 1:        # unique across all markets — safe to use
        return ids[0]
    return None              # ambiguous or missing — caller marks as error


def evaluate_pending_tests(borsdata_client, dry_run: bool = False) -> int:
    """
    Find pending ForwardTests whose check_date <= today.
    Fetch OHLCV from entry_date to check_date, compute MFE/MAE, detect stop trigger.
    Returns number of tests evaluated.
    """
    today = date.today()

    from database.models import ForwardTest, Universe, SessionLocal

    with SessionLocal() as session:
        pending = (
            session.query(ForwardTest)
            .filter(ForwardTest.status == "pending", ForwardTest.check_date <= today)
            .all()
        )

        if not pending:
            return 0

        logger.info("Evaluating %d matured forward tests...", len(pending))

        # universe.borsdata_id is not populated, so resolve ids from Borsdata's
        # instrument lists once for the whole batch (disambiguated by exchange).
        by_exch_ticker, by_ticker = _build_insid_resolver(borsdata_client)
        evaluated = 0

        for ft in pending:
            uni = session.query(Universe).filter(Universe.symbol == ft.symbol).first()
            ins_id = (uni.borsdata_id if (uni and uni.borsdata_id) else None) \
                or _resolve_insid(ft, by_exch_ticker, by_ticker)
            if not ins_id:
                logger.warning("ForwardTest %s (%s): could not resolve Borsdata id, marking error",
                               ft.symbol, ft.exchange)
                ft.status = "error"
                continue

            try:
                df = borsdata_client.get_ohlcv(ins_id, from_date=ft.entry_date)
            except Exception as exc:
                logger.warning("ForwardTest OHLCV fetch failed for %s: %s", ft.symbol, exc)
                ft.status = "error"
                continue

            if df.empty:
                ft.status = "error"
                continue

            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)

            entry_ts = pd.Timestamp(ft.entry_date)
            check_ts = pd.Timestamp(ft.check_date)
            window = df[(df["date"] > entry_ts) & (df["date"] <= check_ts)].copy()

            if window.empty:
                ft.status = "error"
                continue

            entry_price = ft.entry_price
            stop = ft.stop_price  # use current stop_price (may differ from entry_candle_low)

            sl_triggered = False
            sl_trigger_date = None
            peak_high = float("-inf")
            trough_low = float("inf")

            for _, candle in window.iterrows():
                candle_high = float(candle["high"])
                candle_low = float(candle["low"])

                if candle_high > peak_high:
                    peak_high = candle_high
                if candle_low < trough_low:
                    trough_low = candle_low

                if stop and not sl_triggered and candle_low <= stop:
                    sl_triggered = True
                    sl_trigger_date = candle["date"].date()
                    # Freeze MFE/MAE at stop point — don't continue past the stop
                    break

            if peak_high == float("-inf"):
                peak_high = None
            if trough_low == float("inf"):
                trough_low = None

            final_price = float(stop) if sl_triggered and stop else float(window.iloc[-1]["close"])

            if dry_run:
                mfe = ((peak_high / entry_price) - 1) * 100 if (peak_high and entry_price) else 0
                ret = ((final_price / entry_price) - 1) * 100 if entry_price else 0
                logger.info(
                    "  [dry-run] %s | SL=%s | MFE=%.1f%% | Return=%.1f%% | Stop: %s",
                    ft.symbol, sl_triggered, mfe, ret, sl_trigger_date or "—",
                )
                continue

            ft.status = "completed"
            ft.evaluated_at = today
            ft.sl_triggered = sl_triggered
            ft.sl_trigger_date = sl_trigger_date
            ft.max_high = float(peak_high) if peak_high is not None else None
            ft.min_low = float(trough_low) if trough_low is not None else None
            ft.max_mfe_pct = float((peak_high / entry_price) - 1) if (peak_high and entry_price) else None
            ft.max_mae_pct = float((trough_low / entry_price) - 1) if (trough_low and entry_price) else None
            ft.final_price = float(final_price)
            ft.final_return_pct = float((final_price / entry_price) - 1) if entry_price else None
            evaluated += 1

        if not dry_run:
            session.commit()

    logger.info("Forward tests evaluated: %d", evaluated)
    return evaluated

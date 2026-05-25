"""
Nightly pipeline runner.

Usage:
    python run.py                   # full Nordic run
    python run.py --limit 100       # test on first 100 instruments
    python run.py --dry-run         # no DB writes, prints summary
    python run.py --skip-ai         # skip Claude AI assessment
    python run.py --skip-themes     # skip theme classification
    python run.py --exchange STO    # single exchange only (STO/OSL/CPH/HEL)
    python run.py --min-score 65    # only keep signals above this score
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

import pandas as pd

from config.settings import settings
from config.universe_config import EXCHANGES
from data.ingestor import client as borsdata
from database.models import Alert, SessionLocal
from screening.indicators import compute_all, rank_rs_across_universe
from screening.filters import apply_all_hard_filters
from screening.strategies.runner import run_all_strategies
from screening.base_detection import find_base
from themes.refresher import load_hot_themes
from themes.classifier import classify_stock_theme
from scoring.scorer import compute_composite_score
from charts.generator import generate_chart

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

HISTORY_DAYS      = 420      # enough for 200-SMA + 52-week levels + buffer
RS_MIN_PERCENTILE = 70.0     # top 30% relative strength required

# Borsdata marketId → our exchange code
# Indices (isIndex=True) are intentionally excluded.
MARKET_ID_TO_EXCHANGE: dict[int, str] = {
    # Sweden — Stockholm
    1: "STO", 2: "STO", 3: "STO", 4: "STO", 5: "STO", 6: "STO",
    # Norway — Oslo
    9: "OSL", 10: "OSL", 11: "OSL", 12: "OSL", 27: "OSL", 78: "OSL",
    # Finland — Helsinki
    14: "HEL", 15: "HEL", 16: "HEL", 17: "HEL", 30: "HEL",
    # Denmark — Copenhagen
    20: "CPH", 21: "CPH", 22: "CPH", 23: "CPH", 48: "CPH",
    # US (uncomment to include)
    # 32: "NYSE", 33: "NASDAQ",
}

STOCK_INSTRUMENT_TYPE = 0   # Borsdata: 0 = common stock


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="AI Stock Screener pipeline")
    p.add_argument("--limit",       type=int,   default=0,    help="Max instruments (0=all)")
    p.add_argument("--dry-run",     action="store_true",      help="Skip DB writes")
    p.add_argument("--skip-ai",     action="store_true",      help="Skip AI assessment")
    p.add_argument("--skip-themes", action="store_true",      help="Skip theme classification")
    p.add_argument("--exchange",    default="",               help="Filter exchange (STO/OSL/CPH/HEL)")
    p.add_argument("--min-score",   type=float, default=60.0, help="Min composite score for alerts")
    return p.parse_args()


def _safe_round(v, decimals: int = 4):
    try:
        return round(float(v), decimals) if v is not None else None
    except (TypeError, ValueError):
        return None


def main() -> None:
    args = parse_args()

    missing = settings.validate()
    if missing:
        logger.error("Missing required config: %s", ", ".join(missing))
        sys.exit(1)

    today     = date.today()
    from_date = today - timedelta(days=HISTORY_DAYS)
    logger.info("=== Pipeline run: %s  (OHLCV from %s) ===", today, from_date)

    # ------------------------------------------------------------------
    # 1. Universe
    # ------------------------------------------------------------------
    logger.info("Fetching instruments from Borsdata...")
    instruments_df = borsdata.get_instruments()
    if instruments_df.empty:
        logger.error("No instruments returned — check BORSDATA_API_KEY")
        sys.exit(1)

    # Keep only common stocks in known Nordic exchanges
    instruments_df = instruments_df[
        (instruments_df["instrument"] == STOCK_INSTRUMENT_TYPE)
        & instruments_df["marketId"].isin(MARKET_ID_TO_EXCHANGE)
    ].copy()

    if args.exchange:
        target_ids = {mid for mid, ex in MARKET_ID_TO_EXCHANGE.items() if ex == args.exchange}
        instruments_df = instruments_df[instruments_df["marketId"].isin(target_ids)]

    if args.limit:
        instruments_df = instruments_df.head(args.limit)

    logger.info("%d instruments to process", len(instruments_df))

    # ------------------------------------------------------------------
    # 2. OHLCV pass — Stage 2 filter + collect RS inputs
    # ------------------------------------------------------------------
    passing_dfs: dict[str, pd.DataFrame] = {}   # Stage 2 passers, full df
    raw_returns: dict[str, float]        = {}   # all symbols → 63d return
    meta_map:    dict[str, dict]         = {}   # symbol → {name, exchange, currency}

    n_total  = len(instruments_df)
    n_stage2 = 0
    n_skip   = 0

    for i, (_, row) in enumerate(instruments_df.iterrows()):
        ins_id   = int(row["insId"])
        symbol   = str(row.get("ticker") or f"BD{ins_id}")
        name     = str(row.get("name", symbol))
        market_id = int(row["marketId"])
        exchange = MARKET_ID_TO_EXCHANGE.get(market_id, "UNK")
        currency = str(row.get("stockPriceCurrency", ""))
        exc_cfg  = EXCHANGES.get(exchange)

        if i % 100 == 0 and i > 0:
            logger.info("  %d / %d  |  Stage-2 passers: %d", i, n_total, n_stage2)

        try:
            df = borsdata.get_ohlcv(ins_id, from_date=from_date)
        except Exception as exc:
            logger.debug("OHLCV failed %s: %s", symbol, exc)
            n_skip += 1
            continue

        if df.empty or len(df) < 210:
            n_skip += 1
            continue

        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        df = compute_all(df)

        # 63-day return for RS ranking (collected for ALL symbols)
        if len(df) >= 64 and df["close"].iloc[-64] > 0:
            raw_returns[symbol] = (df["close"].iloc[-1] / df["close"].iloc[-64]) - 1

        # Convert value threshold → share count (Borsdata volumes are always in shares).
        # Use 10-day avg close as the price reference — same window as the volume check.
        close_10d = float(df["close"].tail(10).mean()) if len(df) >= 10 else float(df["close"].iloc[-1])
        min_price = exc_cfg.min_price if exc_cfg else 0.0
        if exc_cfg and exc_cfg.volume_unit == "value" and close_10d > 0:
            min_vol = exc_cfg.min_avg_volume / close_10d
        elif exc_cfg:
            min_vol = exc_cfg.min_avg_volume
        else:
            min_vol = 0.0

        # Stage 2 hard filter (RS skipped here — applied after two-pass ranking)
        filt = apply_all_hard_filters(
            df, symbol, rs_rank=0, min_volume=min_vol,
            params={"sma200_trend_weeks": 4, "rs_min_percentile": 0, "min_price": min_price},
        )
        if not filt["passes"]:
            continue

        n_stage2 += 1
        passing_dfs[symbol] = df
        meta_map[symbol] = {"name": name, "exchange": exchange, "currency": currency}

    logger.info("OHLCV pass done: %d / %d passed Stage 2  (%d skipped)",
                n_stage2, n_total, n_skip)

    if not passing_dfs:
        logger.info("No Stage 2 stocks. Exiting.")
        return

    # ------------------------------------------------------------------
    # 3. Two-pass RS ranking
    # ------------------------------------------------------------------
    logger.info("Computing RS ranks across %d symbols...", len(raw_returns))
    rs_ranks = rank_rs_across_universe(raw_returns)

    # ------------------------------------------------------------------
    # 4. Strategy detection on Stage 2 + RS passers
    # ------------------------------------------------------------------
    raw_signals: list[dict] = []

    for symbol, df in passing_dfs.items():
        rs = rs_ranks.get(symbol, 0.0)
        if rs > 0 and rs < RS_MIN_PERCENTILE:
            continue

        result = run_all_strategies(df, symbol)
        if result is None:
            continue

        entry = result.get("pivot_price") or float(df["close"].iloc[-1])
        atr   = float(df["atr_14"].iloc[-1]) if "atr_14" in df.columns else entry * 0.02
        base  = find_base(df, len(df) - 1)
        stop  = base["base_low"] if base else (entry - 2 * atr)
        risk  = entry - stop
        target = (entry + 3 * risk) if risk > 0 else None

        m = meta_map.get(symbol, {})
        result.update({
            "exchange":        m.get("exchange", ""),
            "currency":        m.get("currency", ""),
            "company_name":    m.get("name", symbol),
            "date":            today.isoformat(),
            "rs_rank":         round(rs, 1),
            "entry_price":     _safe_round(entry),
            "stop_price":      _safe_round(stop),
            "target_price":    _safe_round(target),
            "risk_reward":     _safe_round((target - entry) / risk, 2) if (target and risk > 0) else None,
        })
        raw_signals.append(result)

    logger.info("Signals after RS filter: %d", len(raw_signals))
    if not raw_signals:
        logger.info("No signals. Exiting.")
        return

    # ------------------------------------------------------------------
    # 5. Theme classification
    # ------------------------------------------------------------------
    themes = load_hot_themes()
    if themes.get("themes") and not args.skip_themes:
        logger.info("Theme classification (%d signals × %d themes)...",
                    len(raw_signals), len(themes["themes"]))
        for sig in raw_signals:
            m = meta_map.get(sig["symbol"], {})
            t = classify_stock_theme(
                symbol=sig["symbol"],
                company_name=m.get("name", sig["symbol"]),
                sector=m.get("exchange", ""),
                description="",
                themes=themes,
            )
            sig.update(t)
            logger.info("  %-10s  %s (%s)",
                        sig["symbol"], t.get("theme_name") or "none", t.get("fit_strength", "none"))
    else:
        for sig in raw_signals:
            sig["theme_score"] = 0

    # ------------------------------------------------------------------
    # 6. Composite scoring
    # ------------------------------------------------------------------
    for sig in raw_signals:
        sig.update(compute_composite_score(
            runner_score=sig.get("composite_score", 0),
            theme_score=sig.get("theme_score", 0),
            rs_rank=sig.get("rs_rank"),
        ))

    raw_signals.sort(key=lambda s: s["composite_score"], reverse=True)

    # ------------------------------------------------------------------
    # 7. Chart generation
    # ------------------------------------------------------------------
    chart_paths: dict[str, Path] = {}
    logger.info("Generating charts for %d signals...", len(raw_signals))
    for sig in raw_signals:
        sym = sig["symbol"]
        df  = passing_dfs.get(sym)
        if df is None:
            continue
        try:
            path = generate_chart(df, sig, sym)
            chart_paths[sym] = path
            sig["chart_image_path"] = str(path)
        except Exception as exc:
            logger.warning("Chart failed for %s: %s", sym, exc)

    # ------------------------------------------------------------------
    # 8. AI batch assessment
    # ------------------------------------------------------------------
    ai_results: dict[str, dict] = {}
    if not args.skip_ai:
        top = [s for s in raw_signals if s.get("composite_score", 0) >= args.min_score]
        logger.info("AI assessment on %d signals (score ≥ %.0f)...",
                    len(top), args.min_score)
        from ai.agent import assess_batch
        for r in assess_batch(top, chart_paths, min_composite_score=args.min_score):
            ai_results[r["symbol"]] = r

    # ------------------------------------------------------------------
    # 9. Summary
    # ------------------------------------------------------------------
    logger.info("\n%s", "=" * 68)
    logger.info("%-10s  %-6s  %-5s  %-10s  %-4s  %s",
                "Symbol", "Score", "RS", "Strategies", "PQ", "Theme")
    logger.info("-" * 68)
    for sig in raw_signals:
        ai    = ai_results.get(sig["symbol"], {})
        strat = "+".join(s[:3].upper() for s in sig.get("strategies_fired", []))
        logger.info("%-10s  %-6.0f  %-5.0f  %-10s  %-4s  %s",
                    sig["symbol"],
                    sig.get("composite_score", 0),
                    sig.get("rs_rank", 0),
                    strat,
                    str(ai.get("pattern_quality", "—")),
                    sig.get("theme_name", ""))
    logger.info("=" * 68)
    logger.info("Total: %d signals  |  %d with AI assessment", len(raw_signals), len(ai_results))

    # ------------------------------------------------------------------
    # 10. Write to DB
    # ------------------------------------------------------------------
    if args.dry_run:
        logger.info("Dry run — skipping DB writes.")
        return

    logger.info("Writing alerts to Supabase...")
    with SessionLocal() as session:
        session.query(Alert).filter(Alert.date == today).delete()
        for sig in raw_signals:
            ai         = ai_results.get(sig["symbol"], {})
            confidence = ai.get("confidence_score") or sig.get("composite_score", 0)
            # Pack strategies into the narrative prefix so the dashboard can read them
            strat_tag  = "[" + ",".join(sig.get("strategies_fired", [])) + "]"
            narrative  = f"{strat_tag} {ai.get('ai_narrative', '')}".strip()
            session.add(Alert(
                symbol=sig["symbol"],
                date=today,
                entry_price=sig.get("entry_price"),
                stop_price=sig.get("stop_price"),
                target_price=sig.get("target_price"),
                risk_reward=sig.get("risk_reward"),
                confidence_score=round(confidence, 1),
                pattern_quality=ai.get("pattern_quality") or 0,
                ai_narrative=narrative,
                chart_image_path=sig.get("chart_image_path"),
                sent_at=datetime.utcnow(),
            ))
        session.commit()

    logger.info("Done. %d alerts written for %s.", len(raw_signals), today)


if __name__ == "__main__":
    main()

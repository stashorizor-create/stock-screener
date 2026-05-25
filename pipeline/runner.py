"""
Nightly pipeline runner.

Steps:
  1. Load universe (Nordic + US instruments from Borsdata)
  2. Fetch OHLCV for every instrument (Borsdata, rate-limit throttled)
  3. Compute indicators
  4. Apply Stage 2 hard filters + RS rank (computed across full universe)
  5. Run all 5 strategy detectors
  6. Refresh hot themes (Claude, once per run)
  7. For each passing signal:
       a. Classify into hot theme (Claude haiku)
       b. Fetch enrichment (StockTwits, Google Trends)
       c. Compute full composite score
       d. Generate chart PNG
       e. Run AI visual assessment (Claude vision)
  8. Rank by composite score, take top N
  9. Store results in Supabase alerts table

Run manually:
    python -m pipeline.runner
    python -m pipeline.runner --dry-run        (skip DB write, print results)
    python -m pipeline.runner --limit 100      (cap universe size for testing)
    python -m pipeline.runner --skip-ai        (skip Claude vision assessment)
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

TOP_N            = 30       # signals to keep after full scoring
MIN_COMPOSITE    = 40.0     # drop below this before expensive AI step
MIN_HISTORY_ROWS = 220      # need ~220 trading days for all indicators
CHART_DIR        = ROOT / "charts" / "output"

NORDIC_MARKET_IDS = {1, 2, 3, 4, 9, 10, 11, 12, 14, 15, 16, 20, 21, 22, 23}
US_MARKET_IDS     = {32, 33}
ALL_MARKET_IDS    = NORDIC_MARKET_IDS | US_MARKET_IDS

EXCHANGE_MAP = {
    1: "STO", 2: "STO", 3: "STO", 4: "STO",
    9: "OSL", 10: "OSL", 11: "OSL", 12: "OSL",
    14: "HEL", 15: "HEL", 16: "HEL",
    20: "CPH", 21: "CPH", 22: "CPH", 23: "CPH",
    32: "NYSE", 33: "NASDAQ",
}

CURRENCY_MAP = {
    "STO": "SEK", "OSL": "NOK", "HEL": "EUR",
    "CPH": "DKK", "NYSE": "USD", "NASDAQ": "USD",
}

# Minimum 50-day avg volume (shares or currency units depending on exchange)
MIN_VOLUME = {
    "STO": 2_000_000, "OSL": 500_000, "CPH": 1_000_000, "HEL": 200_000,
    "NYSE": 500_000, "NASDAQ": 500_000,
}


# ---------------------------------------------------------------------------
# Step 1: universe
# ---------------------------------------------------------------------------

def _load_universe(limit: int | None = None) -> list[dict]:
    from data.ingestor import client

    logger.info("Loading universe…")
    nordic = client.get_instruments()
    nordic = nordic[nordic["marketId"].isin(NORDIC_MARKET_IDS)].copy()

    glob = client.get_instruments_global()
    us = glob[glob["marketId"].isin(US_MARKET_IDS)].copy()

    combined = pd.concat(
        [nordic[["insId", "ticker", "name", "marketId"]],
         us[["insId", "ticker", "name", "marketId"]]],
        ignore_index=True,
    )
    combined["exchange"] = combined["marketId"].map(EXCHANGE_MAP).fillna("?")
    combined["currency"] = combined["exchange"].map(CURRENCY_MAP).fillna("USD")

    if limit:
        combined = combined.head(limit)

    logger.info("Universe: %d instruments", len(combined))
    return combined.rename(columns={"insId": "ins_id", "ticker": "symbol"}).to_dict("records")


# ---------------------------------------------------------------------------
# Step 2: OHLCV fetch
# ---------------------------------------------------------------------------

def _fetch_ohlcv(ins_id: int, days: int = 420) -> pd.DataFrame:
    from data.ingestor import client
    from_date = date.today() - timedelta(days=days)
    df = client.get_ohlcv(ins_id, from_date=from_date)
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    # Ensure required columns exist
    for col in ["open", "high", "low", "close", "volume"]:
        if col not in df.columns:
            return pd.DataFrame()
    return df


# ---------------------------------------------------------------------------
# Step 3-5: indicators + filters + strategies for one instrument
# ---------------------------------------------------------------------------

def _screen_one(instrument: dict, rs_ranks: dict[str, float]) -> dict | None:
    ins_id   = instrument["ins_id"]
    symbol   = instrument["symbol"]
    exchange = instrument["exchange"]

    try:
        df = _fetch_ohlcv(ins_id)
    except Exception as exc:
        logger.debug("OHLCV fetch failed for %s: %s", symbol, exc)
        return None

    if len(df) < MIN_HISTORY_ROWS:
        return None

    try:
        from screening.indicators import compute_all
        df = compute_all(df)
    except Exception as exc:
        logger.warning("Indicators failed for %s: %s", symbol, exc)
        return None

    rs_rank = rs_ranks.get(symbol)

    try:
        from screening.filters import apply_all_hard_filters
        min_vol = MIN_VOLUME.get(exchange, 500_000)
        filter_result = apply_all_hard_filters(df, symbol, rs_rank or 0, min_vol, {})
        if not filter_result["passes"]:
            return None
    except Exception as exc:
        logger.warning("Hard filter failed for %s: %s", symbol, exc)
        return None

    try:
        from screening.strategies.runner import run_all_strategies
        signal = run_all_strategies(df, symbol)
        if signal is None:
            return None
    except Exception as exc:
        logger.warning("Strategy runner failed for %s: %s", symbol, exc)
        return None

    signal["exchange"]  = exchange
    signal["ins_id"]    = ins_id
    signal["name"]      = instrument.get("name", symbol)
    signal["currency"]  = instrument.get("currency", "USD")
    signal["rs_rank"]   = rs_rank
    signal["_df"]       = df

    return signal


# ---------------------------------------------------------------------------
# Step 6: theme refresh (once per run)
# ---------------------------------------------------------------------------

def _get_themes() -> dict:
    try:
        from themes.refresher import refresh_hot_themes
        return refresh_hot_themes()
    except Exception as exc:
        logger.warning("Theme refresh failed (%s) — loading cached themes", exc)
        from themes.refresher import load_hot_themes
        return load_hot_themes()


# ---------------------------------------------------------------------------
# Step 7: enrich + theme classify + score
# ---------------------------------------------------------------------------

def _enrich(sig: dict) -> None:
    symbol   = sig["symbol"]
    ins_id   = sig.get("ins_id")
    exchange = sig.get("exchange", "")

    # StockTwits — paid API, disabled
    sig["stocktwits_mentions"] = None

    # News (yfinance, no credentials)
    try:
        from enrichment.news import get_news_enrichment
        news = get_news_enrichment(symbol)
        sig["news_sentiment"]  = news.get("news_sentiment")
        sig["news_count_7d"]   = news.get("news_count_7d")
    except Exception:
        sig["news_sentiment"] = None
        sig["news_count_7d"]  = None

    # Google Trends
    try:
        from enrichment.google_trends import get_trends_acceleration
        sig["google_trends_chg"] = get_trends_acceleration(symbol)
    except Exception:
        sig["google_trends_chg"] = None

    # Insider buys
    try:
        from enrichment.insider_buys import get_insider_buys
        sig["insider_buy_days_ago"] = get_insider_buys(symbol, exchange)
    except Exception:
        sig["insider_buy_days_ago"] = None

    # Fundamentals from Borsdata
    if ins_id:
        try:
            from data.ingestor import client
            reports  = client._get(f"/instruments/{ins_id}/reports")
            quarters = reports.get("reportsQuarter", [])
            years    = reports.get("reportsYear", [])

            if len(quarters) >= 2:
                q0, q1 = quarters[-1], quarters[-2]
                eps0, eps1 = q0.get("earnings_Per_Share") or 0, q1.get("earnings_Per_Share") or 0
                rev0, rev1 = q0.get("revenues") or 0, q1.get("revenues") or 0
                sig["eps_qoq"]     = (eps0 - eps1) / abs(eps1) if eps1 else None
                sig["revenue_qoq"] = (rev0 - rev1) / abs(rev1) if rev1 else None

            if len(years) >= 2:
                y0, y1 = years[-1], years[-2]
                epsy0, epsy1 = y0.get("earnings_Per_Share") or 0, y1.get("earnings_Per_Share") or 0
                revy0, revy1 = y0.get("revenues") or 0, y1.get("revenues") or 0
                sig["eps_yoy"]     = (epsy0 - epsy1) / abs(epsy1) if epsy1 else None
                sig["revenue_yoy"] = (revy0 - revy1) / abs(revy1) if revy1 else None
        except Exception as exc:
            logger.debug("Fundamentals fetch failed for %s: %s", symbol, exc)


def _classify_theme(sig: dict, themes: dict) -> dict:
    try:
        from themes.classifier import classify_stock_theme
        return classify_stock_theme(
            symbol       = sig["symbol"],
            company_name = sig.get("name", sig["symbol"]),
            sector       = sig.get("sector", ""),
            description  = "",
            themes       = themes,
        )
    except Exception as exc:
        logger.warning("Theme classification failed for %s: %s", sig["symbol"], exc)
        return {"theme_score": 0, "primary_theme": "none", "theme_name": "",
                "theme_momentum": "", "theme_narrative": "", "fit_strength": "none"}


def _score(sig: dict, theme: dict) -> None:
    from scoring.scorer import compute_composite_score
    breakdown = compute_composite_score(
        runner_score         = sig.get("composite_score", 0),
        theme_score          = theme.get("theme_score", 0),
        rs_rank              = sig.get("rs_rank"),
        eps_yoy              = sig.get("eps_yoy"),
        revenue_yoy          = sig.get("revenue_yoy"),
        eps_qoq              = sig.get("eps_qoq"),
        google_trends_chg    = sig.get("google_trends_chg"),
        insider_buy_days_ago = sig.get("insider_buy_days_ago"),
        news_sentiment       = sig.get("news_sentiment"),
        news_count_7d        = sig.get("news_count_7d"),
        stocktwits_mentions  = sig.get("stocktwits_mentions"),
    )
    sig.update(breakdown)
    sig.update({
        "primary_theme":   theme.get("primary_theme", "none"),
        "theme_name":      theme.get("theme_name", ""),
        "theme_momentum":  theme.get("theme_momentum", ""),
        "theme_narrative": theme.get("theme_narrative", ""),
        "fit_strength":    theme.get("fit_strength", "none"),
    })


# ---------------------------------------------------------------------------
# Step 9: DB write
# ---------------------------------------------------------------------------

def _write_to_db(results: list[dict], run_date: date) -> None:
    import sqlalchemy as sa
    from config.settings import settings

    if not settings.DATABASE_URL:
        logger.warning("DATABASE_URL not set — skipping DB write")
        return

    engine = sa.create_engine(settings.DATABASE_URL)
    rows = [{
        "run_date":           run_date.isoformat(),
        "symbol":             r.get("symbol"),
        "exchange":           r.get("exchange"),
        "alert_type":         r.get("alert_type"),
        "strategies_fired":   r.get("strategies_fired", []),
        "composite_score":    r.get("composite_score"),
        "score_technical":    r.get("score_technical"),
        "score_theme":        r.get("score_theme"),
        "score_rs":           r.get("score_rs"),
        "score_fundamentals": r.get("score_fundamentals"),
        "score_social":       r.get("score_social"),
        "pivot_price":        r.get("pivot_price"),
        "rs_rank":            r.get("rs_rank"),
        "primary_theme":      r.get("primary_theme"),
        "theme_name":         r.get("theme_name"),
        "theme_narrative":    r.get("theme_narrative"),
        "pattern_quality":    r.get("pattern_quality"),
        "ai_narrative":       r.get("ai_narrative"),
        "chart_path":         r.get("chart_path"),
    } for r in results]

    with engine.begin() as conn:
        conn.execute(
            sa.text("""
                INSERT INTO alerts (
                    run_date, symbol, exchange, alert_type, strategies_fired,
                    composite_score, score_technical, score_theme, score_rs,
                    score_fundamentals, score_social, pivot_price, rs_rank,
                    primary_theme, theme_name, theme_narrative,
                    pattern_quality, ai_narrative, chart_path
                ) VALUES (
                    :run_date, :symbol, :exchange, :alert_type, :strategies_fired,
                    :composite_score, :score_technical, :score_theme, :score_rs,
                    :score_fundamentals, :score_social, :pivot_price, :rs_rank,
                    :primary_theme, :theme_name, :theme_narrative,
                    :pattern_quality, :ai_narrative, :chart_path
                )
                ON CONFLICT (run_date, symbol) DO UPDATE SET
                    composite_score = EXCLUDED.composite_score,
                    ai_narrative    = EXCLUDED.ai_narrative,
                    chart_path      = EXCLUDED.chart_path
            """),
            rows,
        )
    logger.info("Wrote %d alerts to Supabase", len(rows))


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run_pipeline(
    dry_run:  bool      = False,
    limit:    int|None  = None,
    top_n:    int       = TOP_N,
    skip_ai:  bool      = False,
) -> list[dict]:

    today = date.today()
    CHART_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Universe
    universe = _load_universe(limit=limit)

    # Pre-compute RS ranks across full universe (requires all close series)
    # For now, set all to 50 — will be replaced once we cache OHLCV in DB
    rs_ranks: dict[str, float] = {}

    # 2-5. Screen
    logger.info("Screening %d instruments…", len(universe))
    raw_signals: list[dict] = []
    for i, inst in enumerate(universe):
        if i % 200 == 0 and i > 0:
            logger.info("  %d / %d screened, %d signals", i, len(universe), len(raw_signals))
        sig = _screen_one(inst, rs_ranks)
        if sig:
            raw_signals.append(sig)

    logger.info("Screening done: %d raw signals", len(raw_signals))
    if not raw_signals:
        logger.warning("No signals — pipeline complete (nothing to assess)")
        return []

    # 6. Hot themes
    themes = _get_themes()

    # 7. Enrich + classify + score
    all_scored: list[dict] = []
    for sig in raw_signals:
        _enrich(sig)
        theme = _classify_theme(sig, themes)
        _score(sig, theme)
        all_scored.append(sig)

    scored = [s for s in all_scored if s["composite_score"] >= MIN_COMPOSITE]

    scored.sort(key=lambda s: s["composite_score"], reverse=True)
    top = scored[:top_n]
    logger.info("Top %d signals (min score %.0f)", len(top), MIN_COMPOSITE)

    # 8. Charts + AI assessment
    final: list[dict] = []
    for sig in top:
        symbol = sig["symbol"]
        df     = sig.pop("_df")

        try:
            from charts.generator import generate_chart
            chart_path = generate_chart(df, sig, symbol, output_dir=CHART_DIR)
            sig["chart_path"] = str(chart_path)
        except Exception as exc:
            logger.warning("Chart failed for %s: %s", symbol, exc)
            sig["chart_path"] = None

        if not skip_ai and sig.get("chart_path"):
            try:
                from ai.agent import assess_signal
                ai = assess_signal(sig, sig["chart_path"])
                if ai:
                    sig["pattern_quality"]  = ai["pattern_quality"]
                    sig["ai_narrative"]     = ai["ai_narrative"]
                    sig["confidence_score"] = ai["confidence_score"]
                    logger.info("  %s  quality=%d/10  confidence=%.0f",
                                symbol, ai["pattern_quality"], ai["confidence_score"])
            except Exception as exc:
                logger.warning("AI assessment failed for %s: %s", symbol, exc)

        final.append(sig)

    # 9. Persist
    if not dry_run:
        _write_to_db(final, today)
    else:
        logger.info("--- DRY RUN RESULTS ---")
        for r in final:
            logger.info(
                "  %-10s  score=%-5.0f  [tech=%.0f theme=%.0f rs=%.0f fund=%.0f soc=%.0f]  theme=%-20s  strategies=%s",
                r["symbol"], r["composite_score"],
                r.get("score_technical", 0), r.get("score_theme", 0),
                r.get("score_rs", 0), r.get("score_fundamentals", 0), r.get("score_social", 0),
                r.get("theme_name", "none")[:20],
                "+".join(r.get("strategies_fired", [])),
            )

    # Always log all scored signals in dry-run regardless of threshold
    if dry_run and not final:
        logger.info("--- ALL SCORED SIGNALS (below threshold) ---")
        for r in sorted(all_scored, key=lambda x: x["composite_score"], reverse=True):
            logger.info(
                "  %-10s  score=%-5.1f  [tech=%.0f theme=%.0f rs=%.0f fund=%.0f soc=%.0f]  eps_yoy=%s  theme=%s",
                r["symbol"], r["composite_score"],
                r.get("score_technical", 0), r.get("score_theme", 0),
                r.get("score_rs", 0), r.get("score_fundamentals", 0), r.get("score_social", 0),
                f'{r["eps_yoy"]:.0%}' if r.get("eps_yoy") is not None else "n/a",
                r.get("theme_name", "none")[:20],
            )

    logger.info("Pipeline complete. %d alerts.", len(final))
    return final


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="Nightly screening pipeline")
    parser.add_argument("--dry-run",  action="store_true", help="Skip DB write, print results")
    parser.add_argument("--limit",    type=int, default=None, help="Cap universe size for testing")
    parser.add_argument("--top-n",    type=int, default=TOP_N)
    parser.add_argument("--skip-ai",  action="store_true", help="Skip AI visual assessment")
    args = parser.parse_args()

    run_pipeline(dry_run=args.dry_run, limit=args.limit, top_n=args.top_n, skip_ai=args.skip_ai)

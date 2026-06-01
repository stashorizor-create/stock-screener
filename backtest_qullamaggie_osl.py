"""
Qullamaggie Breakout Backtest — Oslo Stock Exchange (OSL)
=========================================================
Period  : 2017-01-01 to today
Universe: OSL common stocks passing the 5M NOK/day liquidity filter
Entry   : intraday break above base high — max(open, base_high)
Stop    : low of the entry day
Exit    : daily close below 5 EMA → exit next-day open
Portfolio: max 10 simultaneous positions, 0.5% equity risk per trade
Starting equity: 100,000 NOK

Usage:
    python backtest_qullamaggie_osl.py              # run backtest (use cached data)
    python backtest_qullamaggie_osl.py --refresh    # re-fetch all data from Borsdata
    python backtest_qullamaggie_osl.py --charts     # also generate per-trade charts
    python backtest_qullamaggie_osl.py --charts --max-charts 100
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from data.ingestor import BorsdataClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
OSL_MARKET_IDS   = {9, 10, 11, 12, 27, 78}
FETCH_FROM       = date(2016, 1, 1)    # warmup year before backtest start
BACKTEST_START   = date(2017, 1, 1)
STARTING_EQUITY  = 100_000.0           # NOK
MAX_POSITIONS    = 10
RISK_PER_TRADE   = 0.005               # 0.5% of current equity
MIN_LIQUIDITY    = 5_000_000           # price × 10d avg vol (NOK/day)

OUTPUT_DIR  = ROOT / "backtest_output"
CACHE_DIR   = OUTPUT_DIR / "data_cache"


# ---------------------------------------------------------------------------
# Trade record
# ---------------------------------------------------------------------------
@dataclass
class Trade:
    ticker:          str
    entry_date:      date
    entry_price:     float
    stop_price:      float
    shares:          float
    base_days:       int
    prior_move_pct:  float
    quality_score:   float
    exit_date:       date  | None = None
    exit_price:      float | None = None
    exit_reason:     str   | None = None  # "stop" | "ema5" | "open_positions"
    pending_ema_exit: bool = False


# ---------------------------------------------------------------------------
# Indicators
# ---------------------------------------------------------------------------
def _add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ema_5"]      = df["close"].ewm(span=5,   adjust=False).mean()
    df["sma_10"]     = df["close"].rolling(10).mean()
    df["sma_20"]     = df["close"].rolling(20).mean()
    df["sma_50"]     = df["close"].rolling(50).mean()
    df["vol_sma_10"] = df["volume"].rolling(10).mean()
    df["vol_sma_50"] = df["volume"].rolling(50).mean()
    df["high_52w"]   = df["high"].rolling(252).max()
    return df


# ---------------------------------------------------------------------------
# Breakout detector
# ---------------------------------------------------------------------------
def _quality(prior_move: float, depth: float, base_days: int, vol_drying: bool) -> float:
    score  = min(30.0, 30.0 * (prior_move / 0.40))
    score += max(0.0,  25.0 * (1.0 - depth / 0.30))
    score += 20.0 if 14 <= base_days <= 20 else (10.0 if base_days < 14 else 15.0)
    if vol_drying:
        score += 15.0
    return round(score, 1)


def _detect_breakout(df: pd.DataFrame, t: int) -> dict | None:
    """
    Return a signal dict if day t is a valid Qullamaggie breakout, else None.
    Entry = max(open_t, base_high)  (handles gap-up and intraday break).
    Stop  = low of day t.
    """
    row = df.iloc[t]

    # Basic data quality
    for col in ("sma_50", "high_52w", "vol_sma_10", "vol_sma_50", "ema_5"):
        if pd.isna(row[col]):
            return None

    # Liquidity filter at entry day
    if row["close"] * row["vol_sma_10"] < MIN_LIQUIDITY:
        return None

    # Price above SMA 50 (Stage 2)
    if row["close"] < row["sma_50"]:
        return None

    best: dict | None = None

    for base_days in range(10, 31):
        base_start = t - base_days
        if base_start < 60:
            continue

        # Historical base (exclude last 3 candles to prevent stale-breakout redefinition)
        hist_end   = max(base_start + 5, t - 2)
        hist_slice = df.iloc[base_start:hist_end]
        if len(hist_slice) < 5:
            continue

        base_high = hist_slice["close"].max()
        base_low  = hist_slice["close"].min()
        if base_high <= 0:
            continue

        # Base near 52-week high
        if base_high < row["high_52w"] * 0.75:
            continue

        # Base depth ≤ 30%
        depth = (base_high - base_low) / base_high
        if depth > 0.30:
            continue

        # Did today actually break above the base high?
        if row["high"] <= base_high:
            continue

        # Entry price
        entry_price = float(row["open"]) if row["open"] >= base_high else float(base_high)
        stop_price  = float(row["low"])

        if stop_price >= entry_price:
            continue  # degenerate bar

        # Breakout volume confirmation: today ≥ 1.5× 50d avg
        if row["volume"] < row["vol_sma_50"] * 1.5:
            continue

        # Prior move: look back up to 6 months before base
        prior_start = max(0, base_start - 126)
        prior = df["close"].iloc[prior_start:base_start]
        if len(prior) < 10:
            continue

        prior_low  = prior.min()
        prior_high = prior.max()
        if prior_low <= 0:
            continue

        # Trough must precede peak (genuine uptrend, not a peak-then-trough)
        if prior.idxmin() >= prior.idxmax():
            continue

        prior_move = (prior_high - prior_low) / prior_low
        if prior_move < 0.30:
            continue

        # Volume dry-up in base vs. prior period
        base_vol   = df["volume"].iloc[base_start:t].mean()
        prior_vol  = df["volume"].iloc[prior_start:base_start].mean()
        vol_drying = (base_vol < prior_vol * 0.85) if prior_vol > 0 else False

        q = _quality(prior_move, depth, base_days, vol_drying)
        if best is None or depth < best["_depth"]:
            best = {
                "entry_price":    entry_price,
                "stop_price":     stop_price,
                "base_days":      base_days,
                "prior_move_pct": prior_move,
                "quality_score":  q,
                "_depth":         depth,
            }

    return best


# ---------------------------------------------------------------------------
# Data fetch + cache
# ---------------------------------------------------------------------------
def _load_data(force_refresh: bool = False) -> dict[str, pd.DataFrame]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    index_path = CACHE_DIR / "osl_instruments.csv"
    client = BorsdataClient()

    # Instrument list
    if not index_path.exists() or force_refresh:
        log.info("Fetching OSL instrument list from Borsdata...")
        raw = client.get_instruments()
        osl = raw[
            raw["marketId"].isin(OSL_MARKET_IDS) &
            (raw["instrumentType"] == 0)
        ][["insId", "ticker", "name"]].copy()
        osl.to_csv(index_path, index=False)
        log.info("OSL common stocks: %d", len(osl))
    else:
        osl = pd.read_csv(index_path)

    dfs: dict[str, pd.DataFrame] = {}
    total = len(osl)

    for i, row in enumerate(osl.itertuples(), 1):
        ticker   = str(row.ticker).upper().strip()
        ins_id   = int(row.insId)
        cache_fp = CACHE_DIR / f"{ins_id}_{ticker}.csv"

        if cache_fp.exists() and not force_refresh:
            df = pd.read_csv(cache_fp)
            df["date"] = pd.to_datetime(df["date"]).dt.date
        else:
            try:
                df = client.get_ohlcv(ins_id, from_date=FETCH_FROM, max_count=3000)
                if df.empty:
                    continue
                df.to_csv(cache_fp, index=False)
                time.sleep(0.06)
            except Exception as exc:
                log.warning("OHLCV failed %-8s (%d): %s", ticker, ins_id, exc)
                continue

        if len(df) < 150:
            continue

        df = _add_indicators(df)
        dfs[ticker] = df

        if i % 50 == 0 or i == total:
            log.info("Loaded %3d / %d", i, total)

    log.info("Universe ready: %d OSL stocks", len(dfs))
    return dfs


# ---------------------------------------------------------------------------
# Pre-compute all signals
# ---------------------------------------------------------------------------
def _precompute_signals(dfs: dict[str, pd.DataFrame]) -> dict[date, list[tuple[str, dict]]]:
    """
    Scan every stock's full history once and build a lookup:
        date → [(ticker, signal_dict), ...]
    """
    date_signals: dict[date, list] = defaultdict(list)
    total = len(dfs)

    for i, (ticker, df) in enumerate(dfs.items(), 1):
        for t in range(60, len(df)):
            dt = df["date"].iloc[t]
            if dt < BACKTEST_START:
                continue
            sig = _detect_breakout(df, t)
            if sig:
                date_signals[dt].append((ticker, sig))

        if i % 25 == 0 or i == total:
            log.info("Signal scan %3d / %d  (signals so far: %d)",
                     i, total, sum(len(v) for v in date_signals.values()))

    log.info("Signal pre-computation done: %d breakout days",  len(date_signals))
    return date_signals


# ---------------------------------------------------------------------------
# Portfolio simulation
# ---------------------------------------------------------------------------
def _run_simulation(
    dfs: dict[str, pd.DataFrame],
    date_signals: dict[date, list],
) -> tuple[list[Trade], list[tuple[date, float]]]:

    all_dates = sorted({d for df in dfs.values() for d in df["date"] if d >= BACKTEST_START})

    equity    = STARTING_EQUITY
    portfolio: dict[str, Trade] = {}
    closed:    list[Trade]      = []
    curve:     list[tuple]      = []

    log.info("Simulation: %s → %s  (%d trading days)",
             BACKTEST_START, all_dates[-1], len(all_dates))

    for dt in all_dates:

        # ── 1. Process pending EMA5 exits (detected yesterday, exit at today open) ──
        for ticker in [t for t, tr in portfolio.items() if tr.pending_ema_exit]:
            trade = portfolio[ticker]
            df    = dfs[ticker]
            rows  = df[df["date"] == dt]
            if rows.empty:
                continue
            exit_px = float(rows["open"].iloc[0])
            pnl = (exit_px - trade.entry_price) * trade.shares
            equity += pnl
            trade.exit_date  = dt
            trade.exit_price = exit_px
            trade.exit_reason = "ema5"
            closed.append(trade)

        portfolio = {t: tr for t, tr in portfolio.items() if not tr.pending_ema_exit}

        # ── 2. Check stops and detect EMA5 exits for remaining positions ────────
        to_stop: list[str] = []

        for ticker, trade in portfolio.items():
            df   = dfs[ticker]
            rows = df[df["date"] == dt]
            if rows.empty:
                continue
            row = rows.iloc[0]

            # Stop hit intraday
            if float(row["low"]) < trade.stop_price:
                # Gap-down: open below stop → fill at open
                exit_px = min(float(row["open"]), trade.stop_price)
                pnl = (exit_px - trade.entry_price) * trade.shares
                equity += pnl
                trade.exit_date  = dt
                trade.exit_price = exit_px
                trade.exit_reason = "stop"
                closed.append(trade)
                to_stop.append(ticker)
                continue

            # EMA5 close — flag for exit at next open
            if not pd.isna(row["ema_5"]) and float(row["close"]) < float(row["ema_5"]):
                trade.pending_ema_exit = True

        for ticker in to_stop:
            portfolio.pop(ticker, None)

        # ── 3. Enter new positions ───────────────────────────────────────────────
        slots = MAX_POSITIONS - len(portfolio)
        if slots > 0 and dt in date_signals:
            candidates = [
                (ticker, sig) for ticker, sig in date_signals[dt]
                if ticker not in portfolio
            ]
            candidates.sort(key=lambda x: x[1]["quality_score"], reverse=True)

            for ticker, sig in candidates:
                if slots <= 0:
                    break
                entry_px = float(sig["entry_price"])
                stop_px  = float(sig["stop_price"])
                gap = entry_px - stop_px
                if gap <= 0:
                    continue
                risk_nok = equity * RISK_PER_TRADE
                shares   = risk_nok / gap
                portfolio[ticker] = Trade(
                    ticker=ticker,
                    entry_date=dt,
                    entry_price=entry_px,
                    stop_price=stop_px,
                    shares=shares,
                    base_days=sig["base_days"],
                    prior_move_pct=sig["prior_move_pct"],
                    quality_score=sig["quality_score"],
                )
                slots -= 1

        curve.append((dt, round(equity, 2)))

    # ── 4. Close remaining open positions at last price ──────────────────────
    last_date = all_dates[-1]
    for ticker, trade in portfolio.items():
        df = dfs[ticker]
        last_row = df[df["date"] <= last_date].iloc[-1]
        exit_px  = float(last_row["close"])
        pnl = (exit_px - trade.entry_price) * trade.shares
        equity += pnl
        trade.exit_date   = last_date
        trade.exit_price  = exit_px
        trade.exit_reason = "open_positions"
        closed.append(trade)

    log.info("Simulation done: %d closed trades, final equity %.0f NOK", len(closed), equity)
    return closed, curve


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------
def _stats(trades: list[Trade], curve: list[tuple]) -> dict:
    if not trades:
        return {}

    rets  = [(t.exit_price - t.entry_price) / t.entry_price * 100 for t in trades]
    rmult = [
        (t.exit_price - t.entry_price) / (t.entry_price - t.stop_price)
        for t in trades if (t.entry_price - t.stop_price) > 0
    ]
    wins = [r for r in rets if r > 0]
    loss = [r for r in rets if r <= 0]

    equities = [e for _, e in curve]
    peak = equities[0]; max_dd = 0.0
    for e in equities:
        if e > peak: peak = e
        dd = (peak - e) / peak
        if dd > max_dd: max_dd = dd

    years = (curve[-1][0] - curve[0][0]).days / 365.25
    cagr  = ((equities[-1] / STARTING_EQUITY) ** (1 / years) - 1) * 100 if years > 0 else 0

    return {
        "total_trades":     len(trades),
        "win_rate_pct":     len(wins) / len(rets) * 100,
        "avg_return_pct":   sum(rets) / len(rets),
        "median_return_pct": sorted(rets)[len(rets) // 2],
        "avg_r":            sum(rmult) / len(rmult) if rmult else 0,
        "avg_winner_pct":   sum(wins) / len(wins) if wins else 0,
        "avg_loser_pct":    sum(loss) / len(loss) if loss else 0,
        "best_trade_pct":   max(rets),
        "worst_trade_pct":  min(rets),
        "max_drawdown_pct": max_dd * 100,
        "cagr_pct":         cagr,
        "final_equity_nok": equities[-1],
        "stop_exits":       sum(1 for t in trades if t.exit_reason == "stop"),
        "ema5_exits":       sum(1 for t in trades if t.exit_reason == "ema5"),
        "open_exits":       sum(1 for t in trades if t.exit_reason == "open_positions"),
    }


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
def _save_csv(trades: list[Trade], path: Path) -> None:
    rows = []
    for t in trades:
        ret  = (t.exit_price - t.entry_price) / t.entry_price * 100 if t.exit_price else 0
        rmul = ((t.exit_price - t.entry_price) / (t.entry_price - t.stop_price)
                if t.exit_price and (t.entry_price - t.stop_price) > 0 else 0)
        rows.append({
            "ticker":         t.ticker,
            "entry_date":     t.entry_date,
            "entry_price":    round(t.entry_price, 2),
            "stop_price":     round(t.stop_price, 2),
            "exit_date":      t.exit_date,
            "exit_price":     round(t.exit_price, 2) if t.exit_price else "",
            "exit_reason":    t.exit_reason,
            "return_pct":     round(ret, 2),
            "r_multiple":     round(rmul, 2),
            "shares":         round(t.shares, 4),
            "base_days":      t.base_days,
            "prior_move_pct": round(t.prior_move_pct * 100, 1),
            "quality_score":  t.quality_score,
        })
    pd.DataFrame(rows).sort_values("entry_date").to_csv(path, index=False)
    log.info("Saved %d trades → %s", len(trades), path)


def _save_summary(stats: dict, path: Path) -> None:
    lines = [
        "=" * 54,
        "QULLAMAGGIE OSL BACKTEST — SUMMARY",
        f"Period : {BACKTEST_START} → today",
        f"Equity : {STARTING_EQUITY:,.0f} NOK start  |  max {MAX_POSITIONS} positions",
        f"Risk   : {RISK_PER_TRADE*100:.1f}% per trade (stop = low of entry day)",
        f"Exit   : close < 5 EMA → next open",
        "=" * 54,
        f"Total trades     : {stats['total_trades']}",
        f"Win rate         : {stats['win_rate_pct']:.1f}%",
        f"Avg return       : {stats['avg_return_pct']:+.2f}%",
        f"Median return    : {stats['median_return_pct']:+.2f}%",
        f"Avg R            : {stats['avg_r']:+.2f}R",
        f"Avg winner       : {stats['avg_winner_pct']:+.2f}%",
        f"Avg loser        : {stats['avg_loser_pct']:+.2f}%",
        f"Best trade       : {stats['best_trade_pct']:+.2f}%",
        f"Worst trade      : {stats['worst_trade_pct']:+.2f}%",
        f"Max drawdown     : {stats['max_drawdown_pct']:.1f}%",
        f"CAGR             : {stats['cagr_pct']:.1f}%",
        f"Final equity     : {stats['final_equity_nok']:,.0f} NOK",
        f"Stop exits       : {stats['stop_exits']}",
        f"EMA5 exits       : {stats['ema5_exits']}",
        f"Open at end      : {stats['open_exits']}",
        "=" * 54,
    ]
    text = "\n".join(lines)
    path.write_text(text)
    print("\n" + text)


def _plot_equity(curve: list[tuple], stats: dict, path: Path) -> None:
    dates, equities = zip(*curve)
    fig, ax = plt.subplots(figsize=(14, 6), facecolor="#131722")
    ax.set_facecolor("#131722")
    ax.plot(dates, equities, color="#00CC44", linewidth=1.5)
    ax.axhline(STARTING_EQUITY, color="#7d8590", linestyle="--", linewidth=0.8, alpha=0.6)
    ax.fill_between(dates, STARTING_EQUITY, equities,
                    where=[e >= STARTING_EQUITY for e in equities],
                    alpha=0.12, color="#00CC44")
    ax.fill_between(dates, STARTING_EQUITY, equities,
                    where=[e < STARTING_EQUITY for e in equities],
                    alpha=0.12, color="#FF4444")
    ax.set_title(
        f"Qullamaggie OSL  ·  CAGR {stats['cagr_pct']:.1f}%  ·  "
        f"Max DD {stats['max_drawdown_pct']:.1f}%  ·  "
        f"{stats['total_trades']} trades  ·  Win {stats['win_rate_pct']:.0f}%  ·  "
        f"Avg R {stats['avg_r']:+.2f}",
        color="white", fontsize=11, pad=8,
    )
    ax.set_ylabel("Equity (NOK)", color="#8b949e")
    ax.tick_params(colors="#8b949e")
    for spine in ax.spines.values():
        spine.set_color("#21262d")
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:,.0f}"))
    final = equities[-1]
    ax.annotate(
        f"  {final:,.0f} NOK  ({(final / STARTING_EQUITY - 1) * 100:+.0f}%)",
        xy=(dates[-1], final), color="#00CC44", fontsize=9, va="center",
    )
    fig.tight_layout()
    fig.savefig(str(path), dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    log.info("Equity curve → %s", path)


def _plot_trade(trade: Trade, df: pd.DataFrame, path: Path) -> None:
    entry_rows = df[df["date"] == trade.entry_date]
    exit_rows  = df[df["date"] == trade.exit_date]
    if entry_rows.empty or exit_rows.empty:
        return
    ei = int(entry_rows.index[0])
    xi = int(exit_rows.index[0])
    s  = max(0, ei - 30)
    e  = min(len(df) - 1, xi + 10)

    plot_df = df.iloc[s : e + 1].copy()
    plot_df.index = pd.to_datetime(plot_df["date"])

    addplots = []
    for col, color, lw, ls in [
        ("ema_5",  "#FFD700", 1.6, "--"),
        ("sma_10", "#FFFFFF", 0.9, "-"),
        ("sma_20", "#00CC44", 1.1, "-"),
        ("sma_50", "#4488FF", 1.3, "-"),
    ]:
        if col in plot_df.columns and not plot_df[col].isna().all():
            addplots.append(mpf.make_addplot(
                plot_df[col], color=color, width=lw, linestyle=ls, panel=0
            ))

    ret  = (trade.exit_price - trade.entry_price) / trade.entry_price * 100
    rmul = (trade.exit_price - trade.entry_price) / (trade.entry_price - trade.stop_price)
    col  = "#3fb950" if ret > 0 else "#f85149"
    ttl  = (f"{trade.ticker}  {trade.entry_date} → {trade.exit_date}"
            f"  ({trade.exit_reason})  {ret:+.1f}%  {rmul:+.2f}R")

    try:
        fig, axes = mpf.plot(
            plot_df, type="candle", style="nightclouds",
            title=ttl, volume=True,
            addplot=addplots if addplots else [],
            figsize=(12, 6), panel_ratios=(3, 1),
            tight_layout=True, returnfig=True,
        )
        ax = axes[0]
        entry_x = ei - s
        exit_x  = xi - s
        ax.axvline(entry_x, color="#3fb950", linewidth=1.0, alpha=0.7, linestyle=":")
        ax.axvline(exit_x,  color=col,       linewidth=1.0, alpha=0.7, linestyle=":")
        ax.axhline(trade.entry_price, color="#3fb950", linewidth=0.8, linestyle="--", alpha=0.6)
        ax.axhline(trade.stop_price,  color="#f85149", linewidth=0.8, linestyle="--", alpha=0.6)
        fig.savefig(str(path), dpi=120, bbox_inches="tight")
        plt.close(fig)
    except Exception as exc:
        log.debug("Chart skipped for %s: %s", trade.ticker, exc)
        plt.close("all")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="Qullamaggie OSL backtest")
    parser.add_argument("--refresh",    action="store_true", help="Re-fetch all Borsdata OHLCV")
    parser.add_argument("--charts",     action="store_true", help="Generate per-trade charts")
    parser.add_argument("--max-charts", type=int, default=200,
                        help="Max trade charts to generate (default 200, sorted by |return|)")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Load data
    dfs = _load_data(force_refresh=args.refresh)
    if not dfs:
        log.error("No data loaded — check BORSDATA_API_KEY in .env")
        sys.exit(1)

    # 2. Pre-compute all breakout signals
    log.info("Scanning for Qullamaggie breakout signals...")
    date_signals = _precompute_signals(dfs)

    # 3. Portfolio simulation
    trades, curve = _run_simulation(dfs, date_signals)
    if not trades:
        log.warning("No trades generated — try --refresh or check filter thresholds")
        return

    # 4. Stats + output
    s = _stats(trades, curve)
    _save_csv(trades,     OUTPUT_DIR / "trades.csv")
    _save_summary(s,      OUTPUT_DIR / "summary.txt")
    _plot_equity(curve, s, OUTPUT_DIR / "equity_curve.png")

    # 5. Per-trade charts (optional)
    if args.charts:
        charts_dir = OUTPUT_DIR / "charts"
        charts_dir.mkdir(exist_ok=True)
        sorted_trades = sorted(
            trades,
            key=lambda t: abs((t.exit_price - t.entry_price) / t.entry_price),
            reverse=True,
        )[: args.max_charts]
        log.info("Generating %d trade charts...", len(sorted_trades))
        for i, t in enumerate(sorted_trades, 1):
            if t.ticker not in dfs:
                continue
            ret  = (t.exit_price - t.entry_price) / t.entry_price * 100
            sign = "+" if ret >= 0 else "-"
            fname = f"{i:04d}_{sign}{abs(ret):.0f}pct_{t.ticker}_{t.entry_date}.png"
            _plot_trade(t, dfs[t.ticker], charts_dir / fname)
            if i % 25 == 0:
                log.info("  %d / %d charts done", i, len(sorted_trades))
        log.info("Charts → %s", charts_dir)

    log.info("All output in: %s", OUTPUT_DIR)


if __name__ == "__main__":
    main()

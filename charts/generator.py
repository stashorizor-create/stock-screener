"""
Candlestick chart generator with per-strategy layouts.

Each strategy has its own lookback window, MA set, and annotation style.
Multi-strategy signals produce a side-by-side two-chart page with a
composite score header.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.image as mpimg
import matplotlib.lines as mlines
import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd


OUTPUT_DIR = Path(__file__).parent / "output"

_STRATEGY_LABELS = {
    "vcp":          "VCP (Minervini)",
    "qullamaggie":  "Qullamaggie Setup",
    "ema_pullback": "5 EMA Pullback",
    "gap_up":       "Buyable Gap Up",
    "alex_21ema":   "Alex 21EMA Cloud",
    "ignition":     "Big-Winner Ignition",
    "ema21_inside_day": "21EMA Cloud Inside Day",
}

# MA spec tuples: (column, color, line_width, linestyle, legend_label)
_LAYOUTS: dict[str, dict] = {
    "vcp": {
        "lookback_days": 120,
        "ma_specs": [
            ("sma_20",  "#00CC44", 1.1, "-",  "SMA 20"),
            ("sma_50",  "#4488FF", 1.4, "-",  "SMA 50"),
            ("sma_150", "#FF9900", 1.4, "-",  "SMA 150"),
            ("sma_200", "#FF4444", 1.4, "-",  "SMA 200"),
        ],
    },
    "qullamaggie": {
        "lookback_days": 65,
        "ma_specs": [
            ("sma_10", "#FFFFFF", 1.1, "-", "SMA 10"),
            ("sma_20", "#00CC44", 1.1, "-", "SMA 20"),
        ],
    },
    "ema_pullback": {
        "lookback_days": 35,
        "ma_specs": [
            ("sma_10", "#FFFFFF", 1.1, "-",  "SMA 10"),
            ("sma_20", "#00CC44", 1.1, "-",  "SMA 20"),
            ("sma_50", "#4488FF", 1.4, "-",  "SMA 50"),
            ("ema_5",  "#FFD700", 1.8, "--", "EMA 5"),
        ],
    },
    "gap_up": {
        "lookback_days": 25,
        "ma_specs": [
            ("sma_50", "#4488FF", 1.4, "-", "SMA 50"),
        ],
    },
    "alex_21ema": {
        "lookback_days": 60,
        "ma_specs": [
            ("ema_21",      "#00DD66", 1.3, "-",  "EMA 21"),
            ("ema_21_high", "#4499FF", 0.8, "--", "EMA Hi"),
            ("ema_21_low",  "#4499FF", 0.8, "--", "EMA Lo"),
            ("sma_150",     "#FF9900", 1.4, "-",  "SMA 150"),
            ("sma_200",     "#FF4444", 1.4, "-",  "SMA 200"),
        ],
    },
    "ignition": {
        # long window so the washout low, thrust, and breakout are all visible
        "lookback_days": 250,
        "ma_specs": [
            ("sma_50",  "#4488FF", 1.4, "-", "SMA 50"),
            ("sma_200", "#FF4444", 1.4, "-", "SMA 200"),
        ],
    },
    "ema21_inside_day": {
        "lookback_days": 50,
        "ma_specs": [
            ("ema_21",      "#00DD66", 1.3, "-",  "EMA 21"),
            ("ema_21_high", "#4499FF", 0.8, "--", "EMA Hi"),
            ("ema_21_low",  "#4499FF", 0.8, "--", "EMA Lo"),
            ("sma_50",      "#FF9900", 1.4, "-",  "SMA 50"),
        ],
    },
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_chart(
    df: pd.DataFrame,
    signal: dict,
    symbol: str,
    output_dir: Path | None = None,
    lookback_days: int | None = None,
) -> Path:
    """
    Build an annotated candlestick chart and save it as PNG.

    For a single-strategy signal: one 2-panel chart (price + volume).
    For a multi-strategy signal: two charts side-by-side with a composite
    score banner, both in one PNG.

    Args:
        df: DataFrame with OHLCV + computed indicators. Index must be
            convertible to DatetimeIndex.
        signal: Result dict from run_all_strategies().
        symbol: Ticker symbol string.
        output_dir: Directory to save the PNG. Defaults to charts/output/.
        lookback_days: Override the per-strategy default lookback window.

    Returns:
        Path to the saved PNG file.
    """
    out_dir = output_dir or OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    fired = signal.get("strategies_fired", [])
    if not fired:
        fired = ["vcp"]

    if len(fired) == 1:
        fig, plot_df = _build_single_figure(df, signal, symbol, fired[0], lookback_days)
        run_date = str(plot_df.index[-1].date())
        out_path = out_dir / f"{symbol}_{run_date}.png"
        fig.savefig(str(out_path), dpi=150, bbox_inches="tight")
        plt.close(fig)
        return out_path
    else:
        return _build_multi_figure(df, signal, symbol, fired[:2], out_dir, lookback_days)


# ---------------------------------------------------------------------------
# Figure builders
# ---------------------------------------------------------------------------

def _build_single_figure(
    df: pd.DataFrame,
    signal: dict,
    symbol: str,
    strategy: str,
    lookback_override: int | None = None,
    title: str | None = None,
) -> tuple[plt.Figure, pd.DataFrame]:
    layout = _LAYOUTS.get(strategy, _LAYOUTS["vcp"])
    lookback = lookback_override or layout["lookback_days"]
    plot_df = _prepare_df(df, lookback)

    addplots = _ma_addplots(plot_df, layout["ma_specs"])
    addplots.extend(_extra_addplots(signal, strategy, plot_df))

    if title is None:
        score = signal.get("composite_score", 0.0)
        label = _STRATEGY_LABELS.get(strategy, strategy)
        title = f"{symbol}  —  {label}  —  Score {score:.0f}"

    fig, axes = mpf.plot(
        plot_df,
        type="candle",
        style="nightclouds",
        title=title,
        volume=True,
        addplot=addplots if addplots else [],
        figsize=(14, 8),
        panel_ratios=(3, 1),
        tight_layout=True,
        returnfig=True,
    )

    ax_price = axes[0]
    ax_vol = axes[2] if len(axes) > 2 else axes[1]

    sigs = signal.get("signals", {})
    sig = sigs.get(strategy, {})
    _annotate(ax_price, ax_vol, sig, strategy, plot_df)
    _draw_ma_legend(ax_price, layout["ma_specs"])

    return fig, plot_df


def _build_multi_figure(
    df: pd.DataFrame,
    signal: dict,
    symbol: str,
    strategies: list[str],
    out_dir: Path,
    lookback_override: int | None,
) -> Path:
    tmp_dir = Path(tempfile.mkdtemp())
    try:
        imgs = []
        for strategy in strategies:
            label = _STRATEGY_LABELS.get(strategy, strategy)
            per_score = signal.get("signals", {}).get(strategy, {}).get("quality_score", 0)
            sub_title = f"{label}  —  Quality {per_score:.0f}"
            fig, _ = _build_single_figure(
                df, signal, symbol, strategy, lookback_override, title=sub_title
            )
            tmp_path = tmp_dir / f"{strategy}.png"
            fig.savefig(str(tmp_path), dpi=150, bbox_inches="tight")
            plt.close(fig)
            imgs.append(mpimg.imread(str(tmp_path)))

        n = len(imgs)
        fig_out, axes_out = plt.subplots(1, n, figsize=(14 * n, 9))
        fig_out.patch.set_facecolor("#131722")

        if n == 1:
            axes_out = [axes_out]
        for ax, img in zip(axes_out, imgs):
            ax.imshow(img)
            ax.axis("off")

        score = signal.get("composite_score", 0.0)
        alert_type = signal.get("alert_type", "Signal")
        fig_out.suptitle(
            f"{symbol}  —  {alert_type}  —  Composite Score {score:.0f}/100",
            fontsize=14,
            color="white",
            fontweight="bold",
            y=1.01,
        )

        if "date" in df.columns:
            run_date = str(pd.to_datetime(df["date"].iloc[-1]).date())
        else:
            last_ts = df.index[-1]
            run_date = str(last_ts.date() if hasattr(last_ts, "date") else pd.Timestamp(last_ts).date())
        out_path = out_dir / f"{symbol}_{run_date}.png"
        fig_out.savefig(
            str(out_path),
            dpi=150,
            bbox_inches="tight",
            facecolor=fig_out.get_facecolor(),
        )
        plt.close(fig_out)
        return out_path
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Addplot builders
# ---------------------------------------------------------------------------

def _prepare_df(df: pd.DataFrame, lookback_days: int) -> pd.DataFrame:
    plot_df = df.tail(lookback_days).copy()
    if not isinstance(plot_df.index, pd.DatetimeIndex):
        if "date" in plot_df.columns:
            plot_df = plot_df.set_index("date")
            plot_df.index = pd.to_datetime(plot_df.index)
        else:
            plot_df.index = pd.to_datetime(plot_df.index)
    return plot_df


def _ma_addplots(df: pd.DataFrame, ma_specs: list) -> list:
    plots = []
    for col, color, width, linestyle, _ in ma_specs:
        if col in df.columns and not df[col].isna().all():
            plots.append(
                mpf.make_addplot(df[col], color=color, width=width, linestyle=linestyle, panel=0)
            )
    return plots


def _extra_addplots(signal: dict, strategy: str, plot_df: pd.DataFrame) -> list:
    """Strategy-specific addplots (markers, secondary overlays)."""
    return []


# ---------------------------------------------------------------------------
# Annotation dispatchers
# ---------------------------------------------------------------------------

def _annotate(ax_price, ax_vol, sig: dict, strategy: str, plot_df: pd.DataFrame) -> None:
    n = len(plot_df)
    if strategy == "vcp":
        _ann_vcp(ax_price, sig, n)
    elif strategy == "qullamaggie":
        _ann_qullamaggie(ax_price, sig, n, plot_df)
    elif strategy == "ema_pullback":
        _ann_ema_pullback(ax_price, sig, n, plot_df)
    elif strategy == "gap_up":
        _ann_gap_up(ax_price, sig, n)
    elif strategy == "alex_21ema":
        _ann_alex_21ema(ax_price, sig, n, plot_df)


def _ann_vcp(ax, sig: dict, n: int) -> None:
    pivot = sig.get("pivot_price")
    if pivot:
        _hline(ax, pivot, "#00FF88", "Pivot", n)

    n_c = sig.get("n_contractions", 0)
    vol_txt = "Vol ↓" if sig.get("volume_declining") else "Vol mixed"
    _info_box(ax, f"{n_c} contractions · {vol_txt}")


def _ann_qullamaggie(ax, sig: dict, n: int, plot_df: pd.DataFrame) -> None:
    pivot = sig.get("pivot_price")
    base_low = sig.get("base_low")
    base_days = sig.get("base_days", 0)
    prior_move = sig.get("prior_move_pct", 0)

    if pivot:
        _hline(ax, pivot, "#00FF88", "Pivot", n)
    if base_low:
        _hline(ax, base_low, "#FF8800", "Base low", n)

    base_start_x = n - 1 - base_days
    if base_start_x >= 0:
        ax.axvspan(base_start_x, n - 1, alpha=0.08, color="#FF8800")

    vol_txt = "Vol dry" if sig.get("volume_drying") else "Vol normal"
    _info_box(ax, f"{base_days}d base · +{prior_move * 100:.0f}% prior · {vol_txt}")


def _ann_ema_pullback(ax, sig: dict, n: int, plot_df: pd.DataFrame) -> None:
    entry = sig.get("entry_trigger")
    if entry:
        _hline(ax, entry, "#FFDD00", "Entry ↑", n)

    # Highlight inside day bar
    ax.axvspan(n - 1.4, n - 0.6, alpha=0.18, color="#FFDD00")

    # Shade the prior surge window
    days_since = sig.get("days_since_surge", 0)
    surge_days = sig.get("surge_days", 0)
    if surge_days > 0:
        surge_end_x = n - 1 - days_since
        surge_start_x = surge_end_x - surge_days + 1
        if 0 <= surge_start_x <= n - 1:
            ax.axvspan(surge_start_x - 0.5, surge_end_x + 0.5, alpha=0.12, color="#00BFFF")

    surge_pct = sig.get("surge_move_pct", 0)
    vol_ratio = sig.get("surge_volume_ratio", 0)
    _info_box(ax, f"Surge +{surge_pct * 100:.0f}% · {surge_days}d · Vol ×{vol_ratio:.1f} · Inside day")


def _ann_gap_up(ax, sig: dict, n: int) -> None:
    stop = sig.get("gap_day_low")
    if stop:
        _hline(ax, stop, "#FF4444", "Stop", n)

    # Highlight the gap day bar
    ax.axvspan(n - 1.4, n - 0.6, alpha=0.18, color="#00FF88")

    gap_pct = sig.get("gap_pct", 0)
    vol_ratio = sig.get("volume_ratio", 0)
    _info_box(ax, f"Gap +{gap_pct * 100:.1f}% · Vol ×{vol_ratio:.1f}")


def _ann_alex_21ema(ax, sig: dict, n: int, plot_df: pd.DataFrame) -> None:
    # Shade the cloud band
    if "ema_21_high" in plot_df.columns and "ema_21_low" in plot_df.columns:
        x = range(len(plot_df))
        ax.fill_between(
            x,
            plot_df["ema_21_low"].values,
            plot_df["ema_21_high"].values,
            alpha=0.18,
            color="#4499FF",
        )

    entry = sig.get("entry_trigger")
    stop = sig.get("stop_price")
    if entry:
        _hline(ax, entry, "#00FF88", "Entry ↑", n)
    if stop:
        _hline(ax, stop, "#FF4444", "Stop", n)

    pattern = sig.get("pattern", "P1")
    slope = sig.get("slope_5d_pct", 0)
    quality = sig.get("quality_score", 0)
    _info_box(ax, f"{pattern} · Slope {slope:.1f}% · Score {quality:.0f}")


# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------

def _hline(ax, price: float, color: str, label: str, n_bars: int) -> None:
    ax.axhline(price, color=color, linestyle="--", linewidth=1.2, alpha=0.85)
    ax.text(
        n_bars - 1, price, f"  {label} {price:.2f}",
        color=color, fontsize=7.5, va="bottom", fontweight="bold",
    )


def _info_box(ax, text: str) -> None:
    ax.text(
        0.99, 0.98, text,
        transform=ax.transAxes,
        ha="right", va="top",
        fontsize=7,
        color="white",
        bbox=dict(boxstyle="round,pad=0.3", facecolor="#1a1a2e", alpha=0.7, edgecolor="#444444"),
    )


def _draw_ma_legend(ax, ma_specs: list) -> None:
    handles = [
        mlines.Line2D([], [], color=color, linewidth=width, linestyle=ls, label=label)
        for _, color, width, ls, label in ma_specs
    ]
    ax.legend(handles=handles, loc="upper left", fontsize=7, framealpha=0.25, ncol=len(handles))

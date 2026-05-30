"""
Applies all strategy detectors to a single stock and returns
a composite signal dict with every pattern that fired.
"""
import pandas as pd

from screening.strategies.vcp import detect_vcp
from screening.strategies.qullamaggie import detect_qullamaggie_setup
from screening.strategies.ema_pullback import detect_ema_pullback
from screening.strategies.gap_up import detect_gap_up
from screening.strategies.pocket_pivot import detect_pocket_pivot
from screening.strategies.sma_inside_day import detect_sma_inside_day
from screening.strategies.alex_21ema import detect_alex_21ema


STRATEGY_WEIGHTS = {
    "vcp":            1.0,
    "qullamaggie":    1.0,
    "ema_pullback":   0.8,
    "gap_up":         0.8,
    "pocket_pivot":   0.9,
    "sma_inside_day": 0.85,
    "alex_21ema":     0.95,   # P2 (reclaim backtest) gets +10 quality bonus internally
}


def run_all_strategies(df: pd.DataFrame, symbol: str) -> dict | None:
    """
    Run all 5 strategy detectors against the most recent row in df.
    df must already have indicators computed via compute_all().

    Returns a composite result dict, or None if no strategy fires.
    """
    end_idx = len(df) - 1
    if end_idx < 50:
        return None

    signals: dict[str, dict] = {}

    for name, detect_fn in [
        ("vcp",            lambda: detect_vcp(df, end_idx)),
        ("qullamaggie",    lambda: detect_qullamaggie_setup(df, end_idx)),
        ("ema_pullback",   lambda: detect_ema_pullback(df, end_idx)),
        ("gap_up",         lambda: detect_gap_up(df, end_idx)),
        ("pocket_pivot",   lambda: detect_pocket_pivot(df, end_idx)),
        ("sma_inside_day", lambda: detect_sma_inside_day(df, end_idx)),
        ("alex_21ema",     lambda: detect_alex_21ema(df, end_idx)),
    ]:
        try:
            result = detect_fn()
            if result is not None:
                signals[name] = result
        except Exception as exc:
            # Log but never let one strategy crash the whole run
            import logging
            logging.getLogger(__name__).warning(
                "Strategy %s failed for %s: %s", name, symbol, exc
            )

    if not signals:
        return None

    composite_score = _composite_score(signals)

    return {
        "symbol": symbol,
        "strategies_fired": list(signals.keys()),
        "n_strategies": len(signals),
        "composite_score": composite_score,
        "signals": signals,
        "pivot_price": _best_pivot(signals),
        "alert_type": _alert_type(signals),
    }


def _composite_score(signals: dict[str, dict]) -> float:
    """
    Weighted average of individual quality scores.
    Multiple strategies firing on the same stock boosts the score.
    """
    if not signals:
        return 0.0

    total_weight = 0.0
    weighted_sum = 0.0

    for name, signal in signals.items():
        weight = STRATEGY_WEIGHTS.get(name, 1.0)
        score = signal.get("quality_score", 0.0)
        weighted_sum += score * weight
        total_weight += weight

    base_score = weighted_sum / total_weight if total_weight > 0 else 0.0

    # Bonus for multiple strategies firing on the same stock
    multi_strategy_bonus = min(15.0, (len(signals) - 1) * 7.5)

    return round(min(100.0, base_score + multi_strategy_bonus), 1)


def _best_pivot(signals: dict[str, dict]) -> float | None:
    """Return the pivot price from the highest-priority strategy that has one."""
    for name in ("vcp", "qullamaggie", "ema_pullback", "gap_up", "pocket_pivot", "sma_inside_day", "alex_21ema"):
        if name in signals:
            s = signals[name]
            for key in ("pivot_price", "entry_trigger", "gap_day_high"):
                if key in s:
                    return s[key]
    return None


def _alert_type(signals: dict[str, dict]) -> str:
    """Human-readable summary of which strategies fired."""
    labels = {
        "vcp":            "VCP Setup",
        "qullamaggie":    "Qullamaggie Setup",
        "ema_pullback":   "5 EMA Pullback",
        "gap_up":         "Buyable Gap Up",
        "pocket_pivot":   "Pocket Pivot",
        "sma_inside_day": "SMA Inside Day",
        "alex_21ema":     "21EMA Cloud",
    }
    fired = [labels[k] for k in labels if k in signals]
    return " + ".join(fired) if fired else "No Signal"

"""
Strategy 2: Qullamaggie-Style Breakout Setup

Pre-breakout setup. Shorter, more explosive consolidation than Minervini.
Identifies stocks with a strong prior move coiling in a 14-30 day base,
near the 10-day and 20-day MAs, volume dried up.

Entry trigger (for user): tomorrow's breakout above consolidation high with
volume >200% of average.
"""
import pandas as pd


def detect_qullamaggie_setup(
    df: pd.DataFrame,
    end_idx: int,
    min_prior_move_pct: float = 0.30,
    preferred_prior_move_pct: float = 0.40,
    min_base_days: int = 10,    # ~2 weeks
    max_base_days: int = 30,    # ~6 weeks (trading days)
    max_base_depth_pct: float = 0.30,
    pivot_proximity_pct: float = 0.05,
    base_high_min_vs_52w: float = 0.75,
) -> dict | None:
    """
    Detect a Qullamaggie-style pre-breakout setup.

    Conditions:
    1. Strong prior move (30%+ preferred 40-50%) before the base
    2. Short, tight consolidation (14-30 trading days)
    3. Price near the 10-day and 20-day MAs
    4. Volume dried up in consolidation
    5. Within 5% of consolidation high (near pivot)
    """
    if end_idx < 60:
        return None

    current_close = df["close"].iloc[end_idx]
    high_52w = df["high_52w"].iloc[end_idx]
    sma_10 = df["sma_10"].iloc[end_idx]
    sma_20 = df["sma_20"].iloc[end_idx]
    sma_50 = df["sma_50"].iloc[end_idx]

    if any(pd.isna(v) for v in [high_52w, sma_10, sma_20, sma_50]):
        return None

    # Price must be above 50 SMA
    if current_close < sma_50:
        return None

    # Try base windows from 14-30 trading days
    best: dict | None = None

    for base_days in range(min_base_days, max_base_days + 1):
        if end_idx < base_days + 30:
            continue

        base_start = end_idx - base_days
        base_window = df.iloc[base_start : end_idx + 1]

        # Pivot computed from the historical base only (exclude last 3 candles).
        # Including recent candles would let a stock that broke out 2-3 days ago
        # redefine its own "pivot" upward and trivially pass the proximity check.
        hist_end = max(base_start + 5, end_idx - 2)
        base_window_hist = df.iloc[base_start:hist_end]
        if len(base_window_hist) < 5:
            continue

        base_high = base_window_hist["close"].max()
        base_low = base_window_hist["close"].min()

        if base_high <= 0:
            continue

        # Base near 52-week high
        if base_high < high_52w * base_high_min_vs_52w:
            continue

        depth = (base_high - base_low) / base_high
        if depth > max_base_depth_pct:
            continue

        # Price must be in the buy zone: ≤5% below the historical pivot and ≤5% above it.
        # Beyond the upper bound = breakout already happened, setup is stale.
        if current_close < base_high * (1 - pivot_proximity_pct):
            continue
        if current_close > base_high * (1 + pivot_proximity_pct):
            continue

        # Check prior move (look back up to 6 months before base)
        prior_start = max(0, base_start - 126)
        prior = df["close"].iloc[prior_start:base_start]
        if len(prior) < 10:
            continue

        prior_low = prior.min()
        prior_high = prior.max()
        if prior_low <= 0:
            continue

        # Trough must come before peak (genuine uptrend)
        trough_pos = prior.idxmin()
        peak_pos = prior.idxmax()
        if prior.index.get_loc(trough_pos) >= prior.index.get_loc(peak_pos):
            continue

        prior_move = (prior_high - prior_low) / prior_low
        if prior_move < min_prior_move_pct:
            continue

        # Volume dry-up in base vs prior period
        base_vol_avg = base_window["volume"].mean()
        prior_vol_avg = df["volume"].iloc[prior_start:base_start].mean()
        volume_drying = (
            base_vol_avg < prior_vol_avg * 0.85 if prior_vol_avg > 0 else False
        )

        # Price near 10 and 20 day MAs
        near_sma10 = abs(current_close - sma_10) / sma_10 < 0.05
        near_sma20 = abs(current_close - sma_20) / sma_20 < 0.05
        above_sma10 = current_close >= sma_10
        above_sma20 = current_close >= sma_20

        candidate = {
            "strategy": "qullamaggie",
            "pivot_price": base_high,
            "base_low": base_low,
            "base_days": base_days,
            "base_depth_pct": depth,
            "prior_move_pct": prior_move,
            "strong_prior_move": prior_move >= preferred_prior_move_pct,
            "volume_drying": volume_drying,
            "near_sma10": near_sma10,
            "near_sma20": near_sma20,
            "above_sma10": above_sma10,
            "above_sma20": above_sma20,
            "pct_from_pivot": (base_high - current_close) / base_high,
            "quality_score": _qullamaggie_quality(
                prior_move, depth, base_days, volume_drying,
                above_sma10, above_sma20
            ),
        }

        if best is None or depth < best["base_depth_pct"]:
            best = candidate

    return best


def _qullamaggie_quality(
    prior_move: float,
    depth: float,
    base_days: int,
    volume_drying: bool,
    above_sma10: bool,
    above_sma20: bool,
) -> float:
    score = 0.0
    # Prior move: 40%+ = full 30pts, 30% = 15pts
    score += min(30.0, 30.0 * (prior_move / 0.40))
    # Tight base
    score += max(0.0, 25.0 * (1 - depth / 0.30))
    # Sweet spot length: 14-20 days
    if 14 <= base_days <= 20:
        score += 20.0
    elif base_days < 14:
        score += 10.0
    else:
        score += 15.0
    if volume_drying:
        score += 15.0
    if above_sma10:
        score += 5.0
    if above_sma20:
        score += 5.0
    return round(score, 1)

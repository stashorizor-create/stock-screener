import pandas as pd
import numpy as np


def find_base(
    df: pd.DataFrame,
    end_idx: int,
    min_weeks: int = 4,
    max_weeks: int = 52,
    max_depth_pct: float = 0.35,
    pivot_proximity_pct: float = 0.05,
    base_high_min_vs_52w: float = 0.80,
) -> dict | None:
    """
    Scan backwards from end_idx to find the most recent valid consolidation base.

    Conditions for a valid base:
    - Length between min_weeks and max_weeks
    - Depth (close high-to-low within window) <= max_depth_pct
    - Current price within pivot_proximity_pct of the window's close high
    - Base high >= base_high_min_vs_52w * 52-week high  (filters out bases at market lows)
    - ATR contracting in second half vs first half
    - Volume declining in second half vs first half (quality signal only)

    Requires df to have columns: close, high, low, volume, atr_14, high_52w
    (i.e., compute_all() should be called before this function).

    Returns a dict with base metrics, or None if no valid base found.
    """
    max_lookback = max_weeks * 5
    min_lookback = min_weeks * 5

    if end_idx < min_lookback + 20:
        return None

    current_close = df["close"].iloc[end_idx]
    high_52w = df["high_52w"].iloc[end_idx]

    if pd.isna(high_52w) or high_52w <= 0:
        return None

    best: dict | None = None

    for lookback in range(min_lookback, min(max_lookback, end_idx - 20) + 1, 5):
        start_idx = end_idx - lookback
        window = df.iloc[start_idx : end_idx + 1]

        base_high = window["close"].max()
        base_low = window["close"].min()

        if base_high <= 0:
            continue

        # Base must be forming near the 52-week high, not at a market bottom
        if base_high < high_52w * base_high_min_vs_52w:
            continue

        depth = (base_high - base_low) / base_high
        if depth > max_depth_pct:
            continue

        if current_close < base_high * (1 - pivot_proximity_pct):
            continue

        mid = len(window) // 2
        first_half = window.iloc[:mid]
        second_half = window.iloc[mid:]

        atr_contracting = False
        if first_half["atr_14"].mean() > 0:
            atr_contracting = (
                second_half["atr_14"].mean() < first_half["atr_14"].mean()
            )

        volume_drying = False
        if first_half["volume"].mean() > 0:
            volume_drying = (
                second_half["volume"].mean() < first_half["volume"].mean()
            )

        base_length_weeks = lookback / 5

        candidate = {
            "pivot_price": base_high,
            "base_low": base_low,
            "base_length_weeks": base_length_weeks,
            "base_depth_pct": depth,
            "atr_contracting": atr_contracting,
            "volume_drying": volume_drying,
            "near_pivot": current_close >= base_high * (1 - pivot_proximity_pct),
            "quality_score": _base_quality_score(
                depth, base_length_weeks, atr_contracting, volume_drying
            ),
        }

        if best is None or depth < best["base_depth_pct"]:
            best = candidate

    return best


def _base_quality_score(
    depth: float,
    length_weeks: float,
    atr_contracting: bool,
    volume_drying: bool,
) -> float:
    """
    Heuristic quality score 0-100.
    Tighter depth, sweet-spot length (6-16 weeks), with contraction = higher.
    """
    score = 0.0
    score += max(0.0, 40.0 * (1 - depth / 0.35))
    if 6 <= length_weeks <= 16:
        score += 30.0
    elif 4 <= length_weeks < 6:
        score += 15.0
    elif 16 < length_weeks <= 30:
        score += 20.0
    else:
        score += 5.0
    if atr_contracting:
        score += 15.0
    if volume_drying:
        score += 15.0
    return round(score, 1)

"""
Strategy 5: Pocket Pivot

As described by Kacher & Morales (Virtue of Selfish Investing).
Detected end-of-day. Price above 50 SMA, at or near the 10 or 21 day SMA,
with today's volume exceeding the highest volume on any down day in the
prior 10 sessions.

Entry trigger (for user): same day or next day near the 10/21 SMA.
Stop = below the pocket pivot day low or the 50 SMA.
"""
import pandas as pd


def detect_pocket_pivot(
    df: pd.DataFrame,
    end_idx: int,
    down_day_lookback: int = 10,
    max_extension_pct: float = 0.10,    # max distance above 10/21 SMA to still qualify
) -> dict | None:
    """
    Detect a pocket pivot on end_idx's session.

    Conditions:
    1. Price above 50-day SMA
    2. Price within max_extension_pct above the 10-day or 21-day SMA
       (crosses over OR extends from — not too far extended)
    3. Today's volume > highest volume on any DOWN day in prior 10 sessions
       (down day = today's close < yesterday's close)
    """
    if end_idx < down_day_lookback + 25:
        return None

    current_close = df["close"].iloc[end_idx]
    today_volume = df["volume"].iloc[end_idx]
    sma_10 = df["sma_10"].iloc[end_idx]
    sma_21 = df["sma_21"].iloc[end_idx]
    sma_50 = df["sma_50"].iloc[end_idx]

    if any(pd.isna(v) for v in [sma_10, sma_21, sma_50]):
        return None

    # Must be above 50 SMA
    if current_close < sma_50:
        return None

    # Must be near (not too extended above) 10 or 21 SMA
    above_sma10 = current_close >= sma_10
    above_sma21 = current_close >= sma_21
    near_sma10 = above_sma10 and (current_close - sma_10) / sma_10 <= max_extension_pct
    near_sma21 = above_sma21 and (current_close - sma_21) / sma_21 <= max_extension_pct

    if not (near_sma10 or near_sma21):
        return None

    # Crosses over: yesterday was below the SMA, today is above
    prev_close = df["close"].iloc[end_idx - 1]
    crosses_sma10 = prev_close < sma_10 and current_close >= sma_10
    crosses_sma21 = prev_close < sma_21 and current_close >= sma_21

    # Find max volume on any down day in prior 10 sessions
    max_down_day_volume = _max_down_day_volume(df, end_idx, down_day_lookback)

    if max_down_day_volume is None or max_down_day_volume <= 0:
        return None

    volume_qualifies = today_volume > max_down_day_volume
    if not volume_qualifies:
        return None

    volume_ratio = today_volume / max_down_day_volume
    volume_vs_50d = today_volume / df["volume_sma_50"].iloc[end_idx] if df["volume_sma_50"].iloc[end_idx] > 0 else None

    # Use whichever SMA is most relevant (10 preferred, 21 as fallback)
    reference_sma = sma_10 if near_sma10 else sma_21
    reference_sma_label = "sma_10" if near_sma10 else "sma_21"

    return {
        "strategy": "pocket_pivot",
        "reference_sma": reference_sma_label,
        "reference_sma_value": reference_sma,
        "crosses_over": crosses_sma10 or crosses_sma21,
        "extends_from": not (crosses_sma10 or crosses_sma21),
        "volume_ratio_vs_down_days": volume_ratio,
        "volume_ratio_vs_50d_avg": volume_vs_50d,
        "max_down_day_volume": max_down_day_volume,
        "today_volume": today_volume,
        "pct_above_reference_sma": (current_close - reference_sma) / reference_sma,
        "quality_score": _pocket_pivot_quality(
            volume_ratio, crosses_sma10 or crosses_sma21,
            (current_close - reference_sma) / reference_sma
        ),
    }


def _max_down_day_volume(
    df: pd.DataFrame,
    end_idx: int,
    lookback: int,
) -> float | None:
    """
    Return the highest volume recorded on any down day (close < prior close)
    in the lookback window before end_idx.
    """
    max_vol = None
    for i in range(end_idx - lookback, end_idx):
        if i < 1:
            continue
        if df["close"].iloc[i] < df["close"].iloc[i - 1]:
            vol = df["volume"].iloc[i]
            if max_vol is None or vol > max_vol:
                max_vol = vol
    return max_vol


def _pocket_pivot_quality(
    volume_ratio: float,
    crosses_over: bool,
    pct_above_sma: float,
) -> float:
    score = 0.0
    score += min(40.0, (volume_ratio - 1.0) * 40)
    if crosses_over:
        score += 30.0
    else:
        score += 15.0
    # Tighter to MA = better (within 5% ideal)
    score += max(0.0, 30.0 * (1 - pct_above_sma / 0.10))
    return round(score, 1)

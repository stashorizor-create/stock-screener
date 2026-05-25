"""
Strategy 4: Buyable Gap Up (BGU)

Detected end-of-day. Today's session gapped above the prior day's high
and closed with volume at least 50% above the 2-week (10-day) average.
Can occur anywhere — no Stage 2 requirement.

Entry trigger (for user): continuation entry tomorrow if stock holds above
the gap day's low. Stop = gap day low.
"""
import pandas as pd


def detect_gap_up(
    df: pd.DataFrame,
    end_idx: int,
    min_gap_pct: float = 0.01,          # open must be at least 1% above prev high
    min_volume_ratio: float = 1.50,      # volume >= 150% of 10-day average
    min_close_in_range_pct: float = 0.50, # close must be in upper 50% of day's range
) -> dict | None:
    """
    Detect a buyable gap up on today's (end_idx) session.

    Conditions:
    1. Open > prior day high (true gap, not just a big open)
    2. Close in upper 50% of the day's range (held the gains)
    3. Volume >= 150% of 10-day average
    """
    if end_idx < 15:
        return None

    today_open = df["open"].iloc[end_idx]
    today_close = df["close"].iloc[end_idx]
    today_high = df["high"].iloc[end_idx]
    today_low = df["low"].iloc[end_idx]
    today_volume = df["volume"].iloc[end_idx]

    prev_high = df["high"].iloc[end_idx - 1]
    prev_close = df["close"].iloc[end_idx - 1]

    volume_sma_10 = df["volume_sma_10"].iloc[end_idx]
    volume_sma_50 = df["volume_sma_50"].iloc[end_idx]

    if any(pd.isna(v) for v in [volume_sma_10, prev_high, prev_close]):
        return None

    # True gap: open above prior day's high
    gap_pct = (today_open - prev_high) / prev_high
    if gap_pct < min_gap_pct:
        return None

    # Volume confirmation
    vol_ref = volume_sma_10 if not pd.isna(volume_sma_10) else volume_sma_50
    if vol_ref <= 0:
        return None

    volume_ratio = today_volume / vol_ref
    if volume_ratio < min_volume_ratio:
        return None

    # Close in upper half of day's range
    day_range = today_high - today_low
    if day_range > 0:
        close_position = (today_close - today_low) / day_range
    else:
        close_position = 1.0

    if close_position < min_close_in_range_pct:
        return None

    # Gap size from prior close (total move including pre-gap)
    total_move_pct = (today_close - prev_close) / prev_close

    return {
        "strategy": "gap_up",
        "gap_pct": gap_pct,
        "total_move_pct": total_move_pct,
        "volume_ratio": volume_ratio,
        "close_position_in_range": close_position,
        "gap_day_low": today_low,       # stop level for user
        "gap_day_high": today_high,
        "entry_reference": today_close, # continuation entry near this level
        "quality_score": _gap_quality(
            gap_pct, volume_ratio, close_position, total_move_pct
        ),
    }


def _gap_quality(
    gap_pct: float,
    volume_ratio: float,
    close_position: float,
    total_move_pct: float,
) -> float:
    score = 0.0
    score += min(25.0, gap_pct * 500)
    score += min(30.0, (volume_ratio - 1.5) * 30)
    score += close_position * 25.0
    score += min(20.0, total_move_pct * 100)
    return round(max(0.0, score), 1)

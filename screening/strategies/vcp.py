"""
Strategy 1: Minervini Volatility Contraction Pattern (VCP)

Pre-breakout setup. Identifies stocks coiling near a pivot with 2+ contractions
in both price range and volume. Stage 2 trend required.

Entry trigger (for user, not automated): close above pivot on breakout day
with volume >150% of average.
"""
import pandas as pd


def detect_vcp(
    df: pd.DataFrame,
    end_idx: int,
    min_contractions: int = 2,
    pivot_proximity_pct: float = 0.05,
    base_high_min_vs_52w: float = 0.80,
) -> dict | None:
    """
    Scan for a VCP pattern ending at end_idx.

    A VCP has 2+ successive contractions where each contraction's price range
    and average volume are smaller than the previous one.

    Returns a result dict or None if no VCP found.
    """
    if end_idx < 60:
        return None

    # Minervini Stage 2 trend template — VCP-specific requirement.
    # Other strategies enforce their own lighter conditions internally.
    row = df.iloc[end_idx]
    for col in ("sma_50", "sma_150", "sma_200"):
        if pd.isna(row.get(col)):
            return None
    if not (
        row["close"] > row["sma_50"] and
        row["close"] > row["sma_150"] and
        row["close"] > row["sma_200"] and
        row["sma_50"] > row["sma_150"] and
        row["sma_150"] > row["sma_200"]
    ):
        return None
    # 200 SMA must be higher than it was 4 weeks ago
    _lookback = 20
    if end_idx >= _lookback and not pd.isna(df["sma_200"].iloc[end_idx - _lookback]):
        if df["sma_200"].iloc[end_idx] <= df["sma_200"].iloc[end_idx - _lookback]:
            return None

    current_close = df["close"].iloc[end_idx]
    high_52w = df["high_52w"].iloc[end_idx]

    if pd.isna(high_52w) or high_52w <= 0:
        return None

    # Find contractions by scanning for local highs and lows
    contractions = _find_contractions(df, end_idx, lookback=120)

    if len(contractions) < min_contractions:
        return None

    # The pivot is the most recent contraction high
    latest = contractions[-1]
    pivot = latest["high"]

    # Base high must be near 52-week high
    if pivot < high_52w * base_high_min_vs_52w:
        return None

    # Price must be in the buy zone: within pivot_proximity_pct below OR above the pivot.
    # Above the upper bound means the breakout already happened and the setup is stale.
    if current_close < pivot * (1 - pivot_proximity_pct):
        return None
    if current_close > pivot * (1 + pivot_proximity_pct):
        return None

    # Verify contractions are truly tightening (each range < previous)
    ranges = [c["range_pct"] for c in contractions[-min_contractions:]]
    volumes = [c["avg_volume"] for c in contractions[-min_contractions:]]

    range_tightening = all(
        ranges[i] > ranges[i + 1] for i in range(len(ranges) - 1)
    )
    volume_declining = all(
        volumes[i] > volumes[i + 1] for i in range(len(volumes) - 1)
    )

    if not range_tightening:
        return None

    contraction_depths = [c["range_pct"] for c in contractions[-min_contractions:]]

    return {
        "strategy": "vcp",
        "pivot_price": pivot,
        "n_contractions": len(contractions),
        "contraction_depths": contraction_depths,
        "volume_declining": volume_declining,
        "near_pivot": True,
        "current_close": current_close,
        "pct_from_pivot": (pivot - current_close) / pivot,
        "quality_score": _vcp_quality(
            len(contractions), contraction_depths, volume_declining
        ),
    }


def _find_contractions(
    df: pd.DataFrame, end_idx: int, lookback: int = 120
) -> list[dict]:
    """
    Identify price contractions (local swing highs and lows) within the lookback window.
    A contraction is a move from a local high down to a local low and back to a lower high.
    """
    start_idx = max(0, end_idx - lookback)
    window = df["close"].iloc[start_idx : end_idx + 1]
    highs = df["high"].iloc[start_idx : end_idx + 1]
    lows = df["low"].iloc[start_idx : end_idx + 1]
    volumes = df["volume"].iloc[start_idx : end_idx + 1]

    n = len(window)
    if n < 15:
        return []

    # Find local highs and lows using a simple swing detection
    swing_size = max(3, n // 15)
    local_highs: list[int] = []
    local_lows: list[int] = []

    for i in range(swing_size, n - swing_size):
        if highs.iloc[i] == highs.iloc[i - swing_size : i + swing_size + 1].max():
            local_highs.append(i)
        if lows.iloc[i] == lows.iloc[i - swing_size : i + swing_size + 1].min():
            local_lows.append(i)

    if len(local_highs) < 2:
        return []

    contractions: list[dict] = []

    for i in range(len(local_highs) - 1):
        h1_idx = local_highs[i]
        h2_idx = local_highs[i + 1]

        # Find the lowest low between these two highs
        lows_between = [j for j in local_lows if h1_idx < j < h2_idx]
        if not lows_between:
            continue

        low_idx = min(lows_between, key=lambda j: lows.iloc[j])
        h1 = highs.iloc[h1_idx]
        h2 = highs.iloc[h2_idx]
        low = lows.iloc[low_idx]

        if h1 <= 0:
            continue

        range_pct = (h1 - low) / h1
        avg_vol = volumes.iloc[h1_idx:h2_idx].mean()

        contractions.append({
            "high": h2,
            "low": low,
            "range_pct": range_pct,
            "avg_volume": avg_vol,
            "start_pos": h1_idx,
            "end_pos": h2_idx,
        })

    return contractions


def _vcp_quality(
    n_contractions: int,
    contraction_depths: list[float],
    volume_declining: bool,
) -> float:
    score = 0.0
    score += min(n_contractions * 20, 40)
    if contraction_depths:
        final_depth = contraction_depths[-1]
        score += max(0, 30 * (1 - final_depth / 0.15))
    if volume_declining:
        score += 30
    return round(score, 1)

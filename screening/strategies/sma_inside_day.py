"""
Strategy 6: 20/50 SMA Inside Day Pullback

Continuation entry after a surge. Stock pulls back deeper than the 5 EMA
setup — to the 20 SMA or 50 SMA — then prints an inside day at that level.
Offers better risk/reward than the 5 EMA entry because the support MA is
further from recent highs, giving a tighter stop below the inside day low.

Entry trigger (for user): tomorrow breaks above today's inside day high.
"""
import pandas as pd


def detect_sma_inside_day(
    df: pd.DataFrame,
    end_idx: int,
    surge_lookback: int = 40,            # longer than 5 EMA — deeper pullbacks take more time
    surge_min_days: int = 3,
    surge_min_move_pct: float = 0.07,
    surge_min_volume_ratio: float = 1.4,
    sma_proximity_pct: float = 0.03,     # within 3% of the SMA (checked on today's close)
    inside_day_lookback: int = 3,        # inside day can be up to 3 days before SMA touch
) -> dict | None:
    """
    Detect a 20 SMA or 50 SMA inside day pullback setup.

    Sequence required:
    1. A prior surge: 3+ consecutive up days totalling 7%+ on above-avg volume
    2. An inside day within the last 3 days
    3. Today's close within 3% of the 20 SMA or 50 SMA (price has drifted down to the MA)
    4. Price above 50 SMA

    The inside day and the SMA touch do not need to coincide — the inside day
    can form slightly above the MA, then the stock drifts down to it over 1-3 days.
    Entry trigger is still the inside day's high.
    """
    if end_idx < surge_lookback + 10:
        return None

    current_close = df["close"].iloc[end_idx]
    sma_20 = df["sma_20"].iloc[end_idx]
    sma_50 = df["sma_50"].iloc[end_idx]
    volume_sma_50 = df["volume_sma_50"].iloc[end_idx]

    if any(pd.isna(v) for v in [sma_20, sma_50, volume_sma_50]):
        return None

    if current_close < sma_50:
        return None

    # --- Check price near SMA today ---
    near_sma20 = abs(current_close - sma_20) / sma_20 <= sma_proximity_pct
    near_sma50 = abs(current_close - sma_50) / sma_50 <= sma_proximity_pct

    if not near_sma20 and not near_sma50:
        return None

    anchor_sma = "sma_20" if near_sma20 else "sma_50"
    anchor_value = sma_20 if near_sma20 else sma_50

    # --- Find the most recent inside day within the lookback window ---
    inside_day_idx = None
    for i in range(end_idx, max(end_idx - inside_day_lookback - 1, 0), -1):
        if i < 1:
            break
        if df["high"].iloc[i] < df["high"].iloc[i - 1] and df["low"].iloc[i] > df["low"].iloc[i - 1]:
            inside_day_idx = i
            break

    if inside_day_idx is None:
        return None

    inside_day_high = df["high"].iloc[inside_day_idx]
    inside_day_low = df["low"].iloc[inside_day_idx]
    days_ago = end_idx - inside_day_idx

    # --- Find the prior surge ---
    surge = _find_prior_surge(
        df, end_idx,
        lookback=surge_lookback,
        min_days=surge_min_days,
        min_move_pct=surge_min_move_pct,
        min_volume_ratio=surge_min_volume_ratio,
        volume_sma_50=volume_sma_50,
    )

    if surge is None:
        return None

    return {
        "strategy": "sma_inside_day",
        "anchor_sma": anchor_sma,
        "anchor_value": anchor_value,
        "inside_day_high": inside_day_high,
        "inside_day_low": inside_day_low,
        "inside_day_bars_ago": days_ago,
        "pct_from_sma": (current_close - anchor_value) / anchor_value,
        "surge_move_pct": surge["move_pct"],
        "surge_days": surge["n_days"],
        "surge_volume_ratio": surge["volume_ratio"],
        "days_since_surge": surge["days_ago"],
        "entry_trigger": inside_day_high,
        "quality_score": _sma_inside_day_quality(
            surge["move_pct"],
            surge["volume_ratio"],
            surge["n_days"],
            abs(current_close - anchor_value) / anchor_value,
            anchor_sma,
            days_ago,
        ),
    }


def _find_prior_surge(
    df: pd.DataFrame,
    end_idx: int,
    lookback: int,
    min_days: int,
    min_move_pct: float,
    min_volume_ratio: float,
    volume_sma_50: float,
) -> dict | None:
    closes = df["close"]
    volumes = df["volume"]
    search_start = max(1, end_idx - lookback)

    for start in range(end_idx - min_days, search_start - 1, -1):
        consecutive_up = 0
        for i in range(start, end_idx):
            if closes.iloc[i] > closes.iloc[i - 1]:
                consecutive_up += 1
            else:
                break

        if consecutive_up < min_days:
            continue

        surge_end = start + consecutive_up - 1
        surge_start_price = closes.iloc[start - 1]
        surge_end_price = closes.iloc[surge_end]

        if surge_start_price <= 0:
            continue

        move_pct = (surge_end_price - surge_start_price) / surge_start_price
        if move_pct < min_move_pct:
            continue

        surge_volume_avg = volumes.iloc[start : surge_end + 1].mean()
        volume_ratio = surge_volume_avg / volume_sma_50 if volume_sma_50 > 0 else 0

        if volume_ratio < min_volume_ratio:
            continue

        return {
            "n_days": consecutive_up,
            "move_pct": move_pct,
            "volume_ratio": volume_ratio,
            "days_ago": end_idx - surge_end,
        }

    # Single gap day as surge
    for i in range(end_idx - 1, search_start - 1, -1):
        gap_pct = (df["open"].iloc[i] - df["close"].iloc[i - 1]) / df["close"].iloc[i - 1]
        day_move = (df["close"].iloc[i] - df["close"].iloc[i - 1]) / df["close"].iloc[i - 1]
        day_vol_ratio = volumes.iloc[i] / volume_sma_50 if volume_sma_50 > 0 else 0

        if gap_pct >= 0.03 and day_move >= min_move_pct and day_vol_ratio >= min_volume_ratio:
            return {
                "n_days": 1,
                "move_pct": day_move,
                "volume_ratio": day_vol_ratio,
                "days_ago": end_idx - i,
            }

    return None


def _sma_inside_day_quality(
    surge_move: float,
    volume_ratio: float,
    surge_days: int,
    sma_distance: float,
    anchor_sma: str,
    inside_day_bars_ago: int,
) -> float:
    score = 0.0
    # Surge size
    score += min(30.0, surge_move * 200)
    # Volume on surge
    score += min(20.0, (volume_ratio - 1.0) * 20)
    # Surge duration sweet spot
    if 3 <= surge_days <= 6:
        score += 15.0
    elif surge_days < 3:
        score += 8.0
    else:
        score += 12.0
    # Tighter to SMA = better entry
    score += max(0.0, 15.0 * (1 - sma_distance / 0.03))
    # 20 SMA pullback preferred (more momentum preserved)
    score += 10.0 if anchor_sma == "sma_20" else 5.0
    # Inside day freshness: today = full 10pts, 1 day ago = 7pts, 2-3 days ago = 4pts
    if inside_day_bars_ago == 0:
        score += 10.0
    elif inside_day_bars_ago == 1:
        score += 7.0
    else:
        score += 4.0
    return round(score, 1)

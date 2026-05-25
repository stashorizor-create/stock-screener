"""
Strategy 3: 5 EMA Pullback + Inside Day

Continuation entry after a 4-5 day surge on volume. Stock pulls back
to the 5 EMA and prints an inside day. Price must be above 50 SMA.

Entry trigger (for user): tomorrow breaks above today's inside day high.
"""
import pandas as pd


def detect_ema_pullback(
    df: pd.DataFrame,
    end_idx: int,
    surge_lookback: int = 20,       # how far back to look for the surge
    surge_min_days: int = 3,        # min consecutive up days in surge
    surge_min_move_pct: float = 0.07,   # min total move during surge
    surge_min_volume_ratio: float = 1.4, # surge avg volume vs 50d average
    ema_proximity_pct: float = 0.03,     # how close to 5 EMA counts as "near"
) -> dict | None:
    """
    Detect a 5 EMA pullback + inside day setup.

    Sequence required:
    1. A surge: 3+ consecutive up days (or gap day) totalling 7%+ on above-avg volume
    2. Pullback: price has come back to within 3% of the 5 EMA
    3. Today: inside day (high < yesterday's high AND low > yesterday's low)
    4. Price above 50 SMA throughout
    """
    if end_idx < surge_lookback + 10:
        return None

    current_close = df["close"].iloc[end_idx]
    ema_5 = df["ema_5"].iloc[end_idx]
    sma_50 = df["sma_50"].iloc[end_idx]
    volume_sma_50 = df["volume_sma_50"].iloc[end_idx]

    if any(pd.isna(v) for v in [ema_5, sma_50, volume_sma_50]):
        return None

    if current_close < sma_50:
        return None

    # --- Check inside day ---
    today_high = df["high"].iloc[end_idx]
    today_low = df["low"].iloc[end_idx]
    prev_high = df["high"].iloc[end_idx - 1]
    prev_low = df["low"].iloc[end_idx - 1]

    is_inside_day = today_high < prev_high and today_low > prev_low
    if not is_inside_day:
        return None

    # --- Check price near 5 EMA ---
    near_ema5 = abs(current_close - ema_5) / ema_5 <= ema_proximity_pct
    if not near_ema5:
        return None

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
        "strategy": "ema_pullback",
        "inside_day_high": today_high,
        "inside_day_low": today_low,
        "ema_5": ema_5,
        "pct_from_ema5": (current_close - ema_5) / ema_5,
        "surge_move_pct": surge["move_pct"],
        "surge_days": surge["n_days"],
        "surge_volume_ratio": surge["volume_ratio"],
        "days_since_surge": surge["days_ago"],
        "entry_trigger": today_high,    # break above this tomorrow
        "quality_score": _pullback_quality(
            surge["move_pct"], surge["volume_ratio"], surge["n_days"],
            abs(current_close - ema_5) / ema_5
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
    """
    Look back from end_idx for a surge of 3+ consecutive up days or a gap day
    with a total move of 7%+ on above-average volume.
    """
    closes = df["close"]
    volumes = df["volume"]

    search_start = max(1, end_idx - lookback)

    for start in range(end_idx - min_days, search_start - 1, -1):
        # Check if this could be the start of a surge
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

        # Also check for single gap day as a valid surge start
        return {
            "n_days": consecutive_up,
            "move_pct": move_pct,
            "volume_ratio": volume_ratio,
            "days_ago": end_idx - surge_end,
        }

    # Check for a single gap day as the surge
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


def _pullback_quality(
    surge_move: float,
    volume_ratio: float,
    surge_days: int,
    ema_distance: float,
) -> float:
    score = 0.0
    score += min(30.0, surge_move * 200)
    score += min(25.0, (volume_ratio - 1.0) * 25)
    if 3 <= surge_days <= 6:
        score += 25.0
    elif surge_days < 3:
        score += 15.0
    else:
        score += 10.0
    # Tighter to EMA = better
    score += max(0.0, 20.0 * (1 - ema_distance / 0.03))
    return round(score, 1)

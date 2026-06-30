"""
Strategy: 21 EMA Cloud Inside Day

Same family as the 5 EMA / 20-50 SMA inside-day pullbacks, but the pullback
target is the 21 EMA *cloud* (the ema_21_low..ema_21_high band). A stock surges,
then consolidates back into the rising 21 EMA cloud and prints an inside day in
contact with it. Entry = break of the inside day's upper border.

Sequence required:
  1. A prior surge (run-up): 3+ up days totalling 7%+ on above-avg volume
  2. The 21 EMA cloud is rising (continuation, not a topping pullback)
  3. An inside day within the last 3 days whose range touches the cloud band
  4. Price not extended >1×ATR above the cloud top (it's consolidating AT the cloud)
  5. Price above the 50 SMA (intact uptrend)

Entry trigger (for user): tomorrow breaks above the inside day high.
Stop: inside day low.

Requires columns from compute_all(): ema_21, ema_21_high, ema_21_low, sma_50,
volume_sma_50, atr_14.
"""
import pandas as pd

from screening.strategies.sma_inside_day import _find_prior_surge


def detect_ema21_inside_day(
    df: pd.DataFrame,
    end_idx: int,
    surge_lookback: int = 40,
    surge_min_days: int = 3,
    surge_min_move_pct: float = 0.07,
    surge_min_volume_ratio: float = 1.4,
    inside_day_lookback: int = 3,
    slope_lookback: int = 5,
    atr_extension_limit: float = 1.0,
    contact_tol_atr: float = 0.25,
) -> dict | None:
    if end_idx < surge_lookback + 10:
        return None

    row = df.iloc[end_idx]
    for col in ("ema_21", "ema_21_high", "ema_21_low", "sma_50", "volume_sma_50", "atr_14"):
        if pd.isna(row.get(col, float("nan"))):
            return None

    current_close = float(row["close"])
    ema_mid = float(row["ema_21"])
    ema_hi  = float(row["ema_21_high"])
    ema_lo  = float(row["ema_21_low"])
    sma_50  = float(row["sma_50"])
    vol_sma_50 = float(row["volume_sma_50"])
    atr = float(row["atr_14"])

    if atr <= 0 or vol_sma_50 <= 0:
        return None

    # --- 1. Intact uptrend ---
    if current_close < sma_50:
        return None

    # --- 2. Cloud rising (continuation) ---
    prev_mid = df["ema_21"].iloc[end_idx - slope_lookback]
    if pd.isna(prev_mid) or prev_mid <= 0 or ema_mid < prev_mid:
        return None
    slope_pct = (ema_mid - prev_mid) / prev_mid * 100

    # --- 3. Not extended above the cloud (consolidating AT it, not broken out) ---
    if current_close > ema_hi + atr_extension_limit * atr:
        return None

    # --- 4. Most recent inside day within the lookback window ---
    inside_day_idx = None
    for i in range(end_idx, max(end_idx - inside_day_lookback - 1, 0), -1):
        if i < 1:
            break
        if df["high"].iloc[i] < df["high"].iloc[i - 1] and df["low"].iloc[i] > df["low"].iloc[i - 1]:
            inside_day_idx = i
            break
    if inside_day_idx is None:
        return None

    inside_day_high = float(df["high"].iloc[inside_day_idx])
    inside_day_low  = float(df["low"].iloc[inside_day_idx])
    days_ago = end_idx - inside_day_idx

    # --- 5. Inside day in contact with the cloud (range overlaps the band) ---
    cloud_hi = df["ema_21_high"].iloc[inside_day_idx]
    cloud_lo = df["ema_21_low"].iloc[inside_day_idx]
    if pd.isna(cloud_hi) or pd.isna(cloud_lo):
        return None
    cloud_hi = float(cloud_hi); cloud_lo = float(cloud_lo)
    tol = contact_tol_atr * atr
    in_contact = (inside_day_low <= cloud_hi + tol) and (inside_day_high >= cloud_lo - tol)
    if not in_contact:
        return None

    # --- 6. Prior surge (the run-up) ---
    surge = _find_prior_surge(
        df, end_idx,
        lookback=surge_lookback, min_days=surge_min_days,
        min_move_pct=surge_min_move_pct, min_volume_ratio=surge_min_volume_ratio,
        volume_sma_50=vol_sma_50,
    )
    if surge is None:
        return None

    cloud_mid = (cloud_hi + cloud_lo) / 2
    id_mid = (inside_day_high + inside_day_low) / 2
    contact_dist = abs(id_mid - cloud_mid) / cloud_mid if cloud_mid > 0 else 1.0

    return {
        "strategy": "ema21_inside_day",
        "ema_21_mid": round(ema_mid, 2),
        "ema_21_high": round(cloud_hi, 2),
        "ema_21_low": round(cloud_lo, 2),
        "slope_5d_pct": round(slope_pct, 2),
        "inside_day_high": round(inside_day_high, 2),
        "inside_day_low": round(inside_day_low, 2),
        "inside_day_bars_ago": days_ago,
        "contact_dist_pct": round(contact_dist * 100, 2),
        "surge_move_pct": surge["move_pct"],
        "surge_days": surge["n_days"],
        "surge_volume_ratio": surge["volume_ratio"],
        "days_since_surge": surge["days_ago"],
        "entry_trigger": round(inside_day_high, 2),    # break above this intraday
        "pivot_price": round(inside_day_high, 2),
        "stop_price": round(inside_day_low, 2),
        "quality_score": _quality(surge, contact_dist, days_ago, slope_pct),
    }


def _quality(surge: dict, contact_dist: float, inside_day_bars_ago: int, slope_pct: float) -> float:
    score = 0.0
    score += min(30.0, surge["move_pct"] * 200)              # surge size
    score += min(20.0, (surge["volume_ratio"] - 1.0) * 20)  # surge volume
    n = surge["n_days"]                                       # surge duration sweet spot
    score += 12.0 if 3 <= n <= 6 else (8.0 if n < 3 else 10.0)
    score += max(0.0, 15.0 * (1 - contact_dist / 0.05))      # tighter to the cloud = better
    score += min(13.0, slope_pct * 4)                        # rising-cloud momentum
    if inside_day_bars_ago == 0:                             # inside-day freshness
        score += 10.0
    elif inside_day_bars_ago == 1:
        score += 7.0
    else:
        score += 4.0
    return round(min(100.0, score), 1)

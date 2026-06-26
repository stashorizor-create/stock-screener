"""
Strategy: Big-Winner Ignition

Flags a stock at the EARLY ignition of a potential large multi-month advance,
based on the fingerprint validated in the 10-year anatomy-of-winners study
(see memory: research-big-winners). Durable 5–84x winners shared a recipe:

  deep washout  ->  violent thrust off the low  ->  breakout out of the base
  on expanding volume,  carried by accelerating fundamentals.

This detector captures the PRICE/VOLUME half (washout + thrust + volume
breakout). The fundamental half (EPS acceleration / turn-to-profit) is attached
downstream in run.py and shown on the info sheet — the validated edge is the
COMBINATION, so treat this as a probabilistic filter (~5x lift, not a guarantee).

Requires columns from compute_all(): sma_200, sma_50, atr_14, volume_sma_50.
"""
import numpy as np
import pandas as pd


def detect_ignition(
    df: pd.DataFrame,
    end_idx: int,
    washout_lookback: int = 150,
    min_washout: float = 0.18,        # was >=18% below its own 200d MA at the low
    min_thrust: float = 0.25,         # recovered >=25% off that low
    breakout_lookback: int = 60,      # clearing a 60-day base
    min_vol_surge: float = 1.3,       # 5d volume >= 1.3x the 50d average
    min_days_since_trough: int = 15,
    max_days_since_trough: int = 150,  # catch it EARLY (within ~7 months of the low)
) -> dict | None:
    if end_idx < 200:
        return None

    row = df.iloc[end_idx]
    for col in ("sma_200", "sma_50", "atr_14", "volume_sma_50"):
        if pd.isna(row.get(col, float("nan"))):
            return None

    close = float(row["close"])
    sma200 = float(row["sma_200"])
    vol_sma50 = float(row["volume_sma_50"])
    if sma200 <= 0 or vol_sma50 <= 0:
        return None

    low = df["low"].to_numpy(float)
    high = df["high"].to_numpy(float)
    closev = df["close"].to_numpy(float)
    vol = df["volume"].to_numpy(float)
    sma200a = df["sma_200"].to_numpy(float)

    # ── 1. Deep washout existed: find the trough (lowest low) in the lookback ──
    w0 = max(0, end_idx - washout_lookback)
    ti = w0 + int(np.argmin(low[w0:end_idx + 1]))
    if pd.isna(sma200a[ti]) or sma200a[ti] <= 0:
        return None
    washout_depth = (sma200a[ti] - low[ti]) / sma200a[ti]
    if washout_depth < min_washout:
        return None

    # ── 2. Caught early: trough is recent enough to still be igniting ──
    days_since_trough = end_idx - ti
    if not (min_days_since_trough <= days_since_trough <= max_days_since_trough):
        return None

    # ── 3. Violent thrust off the low ──
    thrust = close / low[ti] - 1 if low[ti] > 0 else 0.0
    if thrust < min_thrust:
        return None

    # ── 4. Breakout out of the base (at/clearing the prior 60-day high) ──
    bo_level = float(np.nanmax(closev[max(0, end_idx - breakout_lookback):end_idx]))
    if bo_level <= 0 or close < bo_level * 0.97:
        return None

    # ── 5. Volume breakout: last 5 days vs the 50-day average ──
    vol_surge = float(np.nanmean(vol[max(0, end_idx - 4):end_idx + 1]) / vol_sma50)
    if vol_surge < min_vol_surge:
        return None

    # ── Descriptive extras ──
    dist_sma200 = close / sma200 - 1
    tr = (high - low) / np.where(closev > 0, closev, np.nan)
    adr_recent = np.nanmean(tr[max(0, end_idx - 9):end_idx + 1])
    adr_prior = np.nanmean(tr[max(0, end_idx - 49):max(0, end_idx - 9)])
    adr_contraction = float(adr_recent / adr_prior) if (adr_prior and not np.isnan(adr_prior)) else None

    stop_price = float(np.nanmin(low[max(0, end_idx - 10):end_idx + 1]))

    quality = _quality_score(washout_depth, thrust, vol_surge, adr_contraction, close, bo_level)

    return {
        "strategy":          "ignition",
        "washout_depth_pct": round(washout_depth * 100, 1),
        "thrust_pct":        round(thrust * 100, 1),
        "vol_surge":         round(vol_surge, 2),
        "adr_contraction":   round(adr_contraction, 2) if adr_contraction is not None else None,
        "dist_sma200_pct":   round(dist_sma200 * 100, 1),
        "days_since_trough": int(days_since_trough),
        "trough_price":      round(float(low[ti]), 2),
        "pivot_price":       round(bo_level, 2),     # base breakout level
        "entry_trigger":     round(bo_level, 2),
        "stop_price":        round(stop_price, 2),
        "quality_score":     quality,
    }


def _quality_score(washout, thrust, vol_surge, adr_contraction, close, bo_level) -> float:
    washout_s = min(25.0, washout / 0.40 * 25)          # 40% below 200d = full
    thrust_s  = min(25.0, thrust / 0.60 * 25)           # 60% off the low = full
    vol_s     = min(25.0, max(0.0, (vol_surge - 1.0) / 0.6 * 25))   # 1.6x = full
    contr_s   = 0.0
    if adr_contraction is not None:
        contr_s = min(15.0, max(0.0, (1.0 - adr_contraction) / 0.30 * 15))  # 0.70 ratio = full
    # decisiveness of the breakout above the base
    bo_s = min(10.0, max(0.0, (close / bo_level - 1.0) / 0.10 * 10)) if bo_level else 0.0
    return round(min(100.0, washout_s + thrust_s + vol_s + contr_s + bo_s), 1)

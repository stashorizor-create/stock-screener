"""
Strategy: Alex's 21DMA Structure Pullback (BO21PB)

Based on Alex's PrimeTrading wiki methodology:
  Pattern 1 — price pulls back into a *rising* 21DMA cloud (EMA21 of close/high/low).

Criteria:
  1. Cloud rising — EMA21(close) slope positive over 5 days
  2. Price in zone — between ema_21_low and ema_21_high + 1×ATR (not extended, not broken)
  3. Higher lows — recent swing lows ascending (trend intact)
  4. Low pullback volume — down-day vol < 75% of 50d average (healthy digestion)
  5. Compression — recent daily ranges tightening vs ATR baseline

Entry trigger: break above ema_21_high (cloud top), or at ema_21 if already in cloud.
Stop: ema_21_low (cloud bottom — structural break = exit).
"""
import pandas as pd


def detect_alex_21ema(
    df: pd.DataFrame,
    end_idx: int,
    atr_extension_limit: float = 1.0,
    slope_lookback: int = 5,
    pullback_lookback: int = 20,
    pullback_vol_threshold: float = 0.75,
) -> dict | None:
    """
    Detect Alex's 21DMA structure pullback.
    Requires ema_21, ema_21_high, ema_21_low, atr_14, volume_sma_50, sma_50 columns.
    """
    if end_idx < 50:
        return None

    row = df.iloc[end_idx]
    for col in ("ema_21", "ema_21_high", "ema_21_low", "atr_14", "volume_sma_50"):
        if pd.isna(row.get(col, float("nan"))):
            return None

    close      = row["close"]
    ema_mid    = row["ema_21"]
    ema_hi     = row["ema_21_high"]
    ema_lo     = row["ema_21_low"]
    atr        = row["atr_14"]
    vol_sma_50 = row["volume_sma_50"]

    if atr <= 0 or vol_sma_50 <= 0:
        return None

    # ── 1. Cloud rising ──────────────────────────────────────────────────────
    prev_mid = df["ema_21"].iloc[end_idx - slope_lookback]
    if pd.isna(prev_mid) or ema_mid <= prev_mid:
        return None
    slope_pct = (ema_mid - prev_mid) / prev_mid * 100

    # ── 2. Price in zone (not below cloud, not extended beyond 1×ATR above) ─
    if close < ema_lo:
        return None
    if close > ema_hi + atr_extension_limit * atr:
        return None

    # ── 3. Prior uptrend: price above 50 SMA ─────────────────────────────────
    sma_50 = df["sma_50"].iloc[end_idx] if "sma_50" in df.columns else None
    if sma_50 is not None and not pd.isna(sma_50) and close < sma_50:
        return None

    # ── 4. Higher lows ────────────────────────────────────────────────────────
    hl_score, n_higher_lows = _check_higher_lows(df, end_idx, pullback_lookback)
    if n_higher_lows < 0:
        return None

    # ── 5. Low-volume pullback ────────────────────────────────────────────────
    vol_score = _pullback_volume_score(df, end_idx, pullback_lookback, vol_sma_50, pullback_vol_threshold)

    # ── 6. Compression ────────────────────────────────────────────────────────
    recent_ranges = (df["high"].iloc[end_idx - 5:end_idx + 1] - df["low"].iloc[end_idx - 5:end_idx + 1]).mean()
    compression_ratio = recent_ranges / atr
    compression_score = max(0.0, min(15.0, (1.0 - compression_ratio) * 30 + 15))

    quality = _quality_score(slope_pct, close, ema_lo, ema_hi, atr, hl_score, vol_score, compression_score)

    entry_trigger = ema_hi if close <= ema_hi else close

    return {
        "strategy":          "alex_21ema",
        "ema_21_mid":        round(ema_mid, 2),
        "ema_21_high":       round(ema_hi, 2),
        "ema_21_low":        round(ema_lo, 2),
        "atr":               round(atr, 2),
        "slope_5d_pct":      round(slope_pct, 2),
        "price_in_cloud":    close <= ema_hi,
        "n_higher_lows":     n_higher_lows,
        "compression_ratio": round(compression_ratio, 2),
        "entry_trigger":     round(entry_trigger, 2),
        "stop_price":        round(ema_lo, 2),
        "quality_score":     quality,
    }


def _check_higher_lows(df: pd.DataFrame, end_idx: int, lookback: int) -> tuple[float, int]:
    lows = df["low"].iloc[max(0, end_idx - lookback):end_idx + 1].values
    swing_lows = [
        lows[i] for i in range(1, len(lows) - 1)
        if lows[i] <= lows[i - 1] and lows[i] <= lows[i + 1]
    ]
    if len(swing_lows) < 2:
        return 10.0, 0
    last, prev = swing_lows[-1], swing_lows[-2]
    if last > prev:
        two_consec = len(swing_lows) >= 3 and swing_lows[-2] > swing_lows[-3]
        return (20.0, 2) if two_consec else (15.0, 1)
    elif last < prev * 0.98:
        return 0.0, -1
    return 8.0, 0


def _pullback_volume_score(
    df: pd.DataFrame, end_idx: int, lookback: int, vol_sma_50: float, threshold: float
) -> float:
    window = df.iloc[max(0, end_idx - lookback):end_idx + 1]
    down_days = window[window["close"] < window["close"].shift(1)]
    if down_days.empty or vol_sma_50 <= 0:
        return 10.0
    ratio = down_days["volume"].mean() / vol_sma_50
    if ratio < threshold:
        return 15.0
    if ratio < 1.0:
        return 10.0
    if ratio < 1.3:
        return 5.0
    return 0.0


def _quality_score(
    slope_pct: float,
    close: float,
    ema_lo: float,
    ema_hi: float,
    atr: float,
    hl_score: float,
    vol_score: float,
    compression_score: float,
) -> float:
    # Cloud slope strength (0-25)
    slope_score = min(25.0, slope_pct * 5)

    # Proximity: in cloud + close to ema_lo = best (0-25)
    cloud_span = max(ema_hi - ema_lo, 0.001) + atr
    dist_above_lo = max(0.0, close - ema_lo)
    proximity_score = max(0.0, min(25.0, (1.0 - dist_above_lo / cloud_span) * 25))

    return round(slope_score + proximity_score + hl_score + vol_score + compression_score, 1)

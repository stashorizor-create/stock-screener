"""
Strategy: Alex's 21EMA Cloud Pullback

Two patterns, one entry trigger:

  Pattern 1 (P1) — Rising Pullback
    Price was above cloud, pulled back into it. Cloud rising. Buy the dip.

  Pattern 2 (P2) — Reclaim Backtest  [highest R/R]
    Price briefly violated below cloud, reclaimed it, now back-testing from above.
    Trapped shorts = explosive when it works. Alex's favourite.

Entry trigger (both patterns): prior day high reclaim
    Today's close > yesterday's high while in the valid setup zone.
    EOD signal — confirms demand on the reclaim bar.

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
    violation_lookback: int = 15,
) -> dict | None:
    """
    Detect Alex's 21EMA cloud pullback (P1 or P2) with prior day high reclaim trigger.
    Requires: ema_21, ema_21_high, ema_21_low, atr_14, volume_sma_50, sma_50 columns.
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

    # ── 1. Cloud rising ───────────────────────────────────────────────────────
    prev_mid = df["ema_21"].iloc[end_idx - slope_lookback]
    if pd.isna(prev_mid) or ema_mid <= prev_mid:
        return None
    slope_pct = (ema_mid - prev_mid) / prev_mid * 100

    # ── 2. Price in zone (not below cloud, not extended >1×ATR above top) ────
    if close < ema_lo:
        return None
    if close > ema_hi + atr_extension_limit * atr:
        return None

    # ── 3. Prior uptrend: price above SMA50 ──────────────────────────────────
    sma_50 = df["sma_50"].iloc[end_idx] if "sma_50" in df.columns else None
    if sma_50 is not None and not pd.isna(sma_50) and close < sma_50:
        return None

    # ── 4. Pattern classification ─────────────────────────────────────────────
    # P2: prior cloud violation (close < ema_lo) in the lookback window
    lb_start = max(0, end_idx - violation_lookback)
    prior_closes  = df["close"].iloc[lb_start : end_idx - 1]
    prior_ema_los = df["ema_21_low"].iloc[lb_start : end_idx - 1]
    had_violation = (prior_closes < prior_ema_los).any() if len(prior_closes) > 0 else False

    # P1: was clearly above cloud in last 10 bars (pure pullback, no prior break)
    prior_10_closes = df["close"].iloc[max(0, end_idx - 11) : end_idx - 1]
    was_above_cloud = (prior_10_closes > ema_hi).any() if len(prior_10_closes) > 0 else False

    pat2 = had_violation                   # reclaim backtest
    pat1 = was_above_cloud and not pat2    # clean rising pullback

    if not pat1 and not pat2:
        return None

    pattern = "P2" if pat2 else "P1"

    # ── 5. Entry trigger: prior day high reclaim ──────────────────────────────
    # Signal only fires on the bar where today's close reclaims yesterday's high.
    prev_high = df["high"].iloc[end_idx - 1]
    if pd.isna(prev_high) or close <= prev_high:
        return None

    # ── 6. Higher lows ────────────────────────────────────────────────────────
    hl_score, n_higher_lows = _check_higher_lows(df, end_idx, pullback_lookback)
    if n_higher_lows < 0:
        return None

    # ── 7. Low-volume pullback ────────────────────────────────────────────────
    vol_score = _pullback_volume_score(df, end_idx, pullback_lookback, vol_sma_50, pullback_vol_threshold)

    # ── 8. Compression ────────────────────────────────────────────────────────
    recent_ranges  = (df["high"].iloc[end_idx - 5 : end_idx + 1]
                      - df["low"].iloc[end_idx - 5 : end_idx + 1]).mean()
    compression_ratio = recent_ranges / atr
    compression_score = max(0.0, min(15.0, (1.0 - compression_ratio) * 30 + 15))

    quality = _quality_score(
        slope_pct, close, ema_lo, ema_hi, atr,
        hl_score, vol_score, compression_score,
        pattern_bonus=10.0 if pat2 else 0.0,
    )

    return {
        "strategy":          "alex_21ema",
        "pattern":           pattern,
        "ema_21_mid":        round(ema_mid, 2),
        "ema_21_high":       round(ema_hi, 2),
        "ema_21_low":        round(ema_lo, 2),
        "atr":               round(atr, 2),
        "slope_5d_pct":      round(slope_pct, 2),
        "price_in_cloud":    close <= ema_hi,
        "n_higher_lows":     n_higher_lows,
        "compression_ratio": round(compression_ratio, 2),
        "entry_trigger":     round(close, 2),       # triggered at today's close
        "stop_price":        round(ema_lo, 2),
        "quality_score":     quality,
    }


def _check_higher_lows(df: pd.DataFrame, end_idx: int, lookback: int) -> tuple[float, int]:
    lows = df["low"].iloc[max(0, end_idx - lookback) : end_idx + 1].values
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
    window    = df.iloc[max(0, end_idx - lookback) : end_idx + 1]
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
    pattern_bonus: float = 0.0,
) -> float:
    # Cloud slope strength (0-25)
    slope_score = min(25.0, slope_pct * 5)

    # Proximity: deep in cloud near ema_lo = best (0-25)
    cloud_span    = max(ema_hi - ema_lo, 0.001) + atr
    dist_above_lo = max(0.0, close - ema_lo)
    proximity_score = max(0.0, min(25.0, (1.0 - dist_above_lo / cloud_span) * 25))

    # P2 gets a bonus for higher R/R (trapped shorts, explosive potential)
    return round(
        min(100.0, slope_score + proximity_score + hl_score + vol_score + compression_score + pattern_bonus),
        1,
    )

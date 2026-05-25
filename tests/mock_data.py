"""
Synthetic OHLCV generators for testing the screener pipeline without live data.
Uses deterministic price paths so tests are not seed-dependent.
"""
import numpy as np
import pandas as pd


def make_stage2_base(seed: int = 42) -> pd.DataFrame:
    """
    Synthetic stock in a valid Stage 2 base near pivot.
    Should PASS all hard filters.

    Price structure (400 trading days):
      - Days   0-279: deterministic uptrend 50 → 100  (+100%)
      - Days 280-349: tight base oscillation around 91 (depth ≈ 8%, ATR/vol contracting)
      - Days 350-399: linear approach 91 → 97 (near pivot at 100)

    SMA alignment at day 399:
      SMA(50)  ≈ 94  — covers only the approach (rising)
      SMA(150) ≈ 95  — covers last 30 days of uptrend + base + approach
      SMA(200) ≈ 92  — reaches further into the lower part of the uptrend
      → close(97) > SMA50(94) > SMA150(95)? No — let me be explicit below.

    Actual expected alignment with these numbers:
      - SMA(200) window covers days 200-399: includes uptrend from 85→100, then base, then approach.
        Uptrend tail is 80 days (85→100, mean≈92.5); base 70 days (mean≈91); approach 50 days (mean≈94).
        SMA(200) ≈ (80*92.5 + 70*91 + 50*94)/200 ≈ 92.2
      - SMA(150) window covers days 250-399: uptrend last 30 days (96.4→100, mean≈98.2); base+approach same.
        SMA(150) ≈ (30*98.2 + 70*91 + 50*94)/150 ≈ 94.0
      - SMA(50) window covers days 350-399: approach only, mean≈94.
      - close≈97 > SMA50≈94 > SMA150≈94... tight.

    To get clear separation, use uptrend that goes to 80 before base, base around 74, approach to 78.
    This way the 200-day window still reaches back into lower prices.
    """
    rng = np.random.default_rng(seed)
    n_total = 400
    dates = pd.bdate_range(end=pd.Timestamp.today(), periods=n_total)

    # Uptrend: 280 days, 50→100. Day 200 value ≈ 85.7, Day 250 value ≈ 94.6
    uptrend_n = 280
    uptrend_core = np.linspace(50.0, 100.0, uptrend_n)
    uptrend_noise = rng.normal(0, 0.6, uptrend_n)
    uptrend_close = uptrend_core + uptrend_noise

    # Base: 70 days, tight sine oscillation around 91, contracting amplitude
    base_n = 70
    base_center = 91.0
    t_base = np.linspace(0, 2 * np.pi, base_n)
    amplitude = np.linspace(3.5, 0.8, base_n)
    base_core = base_center + amplitude * np.sin(t_base)
    base_noise_scale = np.linspace(0.45, 0.12, base_n)
    base_noise = rng.normal(0, 1.0, base_n) * base_noise_scale
    base_close = base_core + base_noise

    # Approach: 50 days, deterministic rise to near pivot
    approach_n = 50
    approach_start = float(base_close[-1])
    approach_end = 97.0
    approach_core = np.linspace(approach_start, approach_end, approach_n)
    approach_noise = rng.normal(0, 0.3, approach_n)
    approach_close = approach_core + approach_noise

    closes = np.concatenate([uptrend_close, base_close, approach_close])
    closes = np.maximum(closes, 1.0)

    noise_h = np.abs(rng.normal(0.007, 0.003, n_total))
    noise_l = np.abs(rng.normal(0.007, 0.003, n_total))
    highs = closes * (1 + noise_h)
    lows = closes * (1 - noise_l)
    opens = np.concatenate([[closes[0]], closes[:-1]])
    opens = opens * (1 + rng.normal(0, 0.003, n_total))

    # Volume declining in base
    vol_base = rng.lognormal(13.0, 0.25, n_total)
    vol_base[uptrend_n : uptrend_n + base_n] *= np.linspace(1.0, 0.4, base_n)
    volumes = np.maximum(vol_base, 1).astype(int)

    return pd.DataFrame({
        "date": dates,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    }).set_index("date")


def make_downtrend(seed: int = 7) -> pd.DataFrame:
    """Declining stock. Should FAIL all Stage 2 filters."""
    rng = np.random.default_rng(seed)
    n = 400
    dates = pd.bdate_range(end=pd.Timestamp.today(), periods=n)
    core = np.linspace(100.0, 45.0, n)
    noise = rng.normal(0, 0.8, n)
    closes = np.maximum(core + noise, 1.0)
    noise_h = np.abs(rng.normal(0.007, 0.003, n))
    noise_l = np.abs(rng.normal(0.007, 0.003, n))
    volumes = rng.lognormal(13, 0.3, n).astype(int)
    return pd.DataFrame({
        "date": dates,
        "open": np.concatenate([[closes[0]], closes[:-1]]),
        "high": closes * (1 + noise_h),
        "low": closes * (1 - noise_l),
        "close": closes,
        "volume": volumes,
    }).set_index("date")


def make_choppy_sideways(seed: int = 99) -> pd.DataFrame:
    """Flat, choppy stock. Should FAIL Stage 2 (no trend alignment)."""
    rng = np.random.default_rng(seed)
    n = 400
    dates = pd.bdate_range(end=pd.Timestamp.today(), periods=n)
    t = np.linspace(0, 8 * np.pi, n)
    core = 40.0 + 5.0 * np.sin(t)
    noise = rng.normal(0, 1.5, n)
    closes = np.maximum(core + noise, 1.0)
    noise_h = np.abs(rng.normal(0.01, 0.004, n))
    noise_l = np.abs(rng.normal(0.01, 0.004, n))
    volumes = rng.lognormal(12, 0.4, n).astype(int)
    return pd.DataFrame({
        "date": dates,
        "open": np.concatenate([[closes[0]], closes[:-1]]),
        "high": closes * (1 + noise_h),
        "low": closes * (1 - noise_l),
        "close": closes,
        "volume": volumes,
    }).set_index("date")

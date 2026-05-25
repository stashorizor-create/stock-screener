import pandas as pd


def passes_stage2_trend(row: pd.Series) -> tuple[bool, list[str]]:
    """
    Minervini Stage 2 trend structure. Returns (passes, failed_reasons).
    All five SMA conditions must hold simultaneously.
    """
    checks = {
        "close > sma_50": row["close"] > row["sma_50"],
        "close > sma_150": row["close"] > row["sma_150"],
        "close > sma_200": row["close"] > row["sma_200"],
        "sma_50 > sma_150": row["sma_50"] > row["sma_150"],
        "sma_150 > sma_200": row["sma_150"] > row["sma_200"],
    }
    failed = [k for k, v in checks.items() if not v]
    return len(failed) == 0, failed


def passes_sma200_trend(df: pd.DataFrame, end_idx: int, weeks: int = 4) -> bool:
    """200-day SMA must be higher today than N weeks ago."""
    lookback = weeks * 5
    if end_idx < lookback:
        return False
    sma200 = df["sma_200"]
    if pd.isna(sma200.iloc[end_idx]) or pd.isna(sma200.iloc[end_idx - lookback]):
        return False
    return sma200.iloc[end_idx] > sma200.iloc[end_idx - lookback]


def passes_52w_proximity(close: float, high_52w: float, max_below_pct: float = 0.25) -> bool:
    """Price must be within max_below_pct of the 52-week high."""
    if high_52w <= 0:
        return False
    return close >= high_52w * (1 - max_below_pct)


def passes_rs_rank(rs_rank: float, min_percentile: float = 70.0) -> bool:
    """Stock must be in the top 30% of the universe by 63-day return."""
    return rs_rank >= min_percentile


def passes_liquidity(avg_volume_50d: float, min_volume: float) -> bool:
    return avg_volume_50d >= min_volume


def apply_all_hard_filters(
    df: pd.DataFrame,
    symbol: str,
    rs_rank: float,
    min_volume: float,
    params: dict,
) -> dict:
    """
    Run all hard filters against the most recent row in df.
    Returns a result dict with pass/fail per filter and an overall `passes` bool.
    """
    if len(df) < 200:
        return {"passes": False, "reason": "insufficient_history"}

    row = df.iloc[-1]
    end_idx = len(df) - 1

    stage2_pass, stage2_failures = passes_stage2_trend(row)
    sma200_pass = passes_sma200_trend(df, end_idx, weeks=params.get("sma200_trend_weeks", 4))
    prox_pass = passes_52w_proximity(row["close"], row["high_52w"])
    liq_pass = passes_liquidity(row["volume_sma_50"], min_volume)

    # RS rank filter only applied when a real rank is available (skip if None or 0)
    min_rs = params.get("rs_min_percentile", 70.0)
    rs_pass = (rs_rank is None) or (rs_rank == 0) or passes_rs_rank(rs_rank, min_rs)

    all_pass = stage2_pass and sma200_pass and prox_pass and rs_pass and liq_pass

    return {
        "symbol": symbol,
        "passes": all_pass,
        "stage2_trend": stage2_pass,
        "stage2_failures": stage2_failures,
        "sma200_trending": sma200_pass,
        "near_52w_high": prox_pass,
        "rs_rank_pass": rs_pass,
        "liquidity_pass": liq_pass,
        "close": row["close"],
        "rs_rank": rs_rank,
    }

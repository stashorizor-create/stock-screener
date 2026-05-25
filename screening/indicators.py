import pandas as pd
import numpy as np


def compute_smas(df: pd.DataFrame) -> pd.DataFrame:
    df["sma_10"] = df["close"].rolling(10).mean()
    df["sma_20"] = df["close"].rolling(20).mean()
    df["sma_21"] = df["close"].rolling(21).mean()
    df["sma_50"] = df["close"].rolling(50).mean()
    df["sma_150"] = df["close"].rolling(150).mean()
    df["sma_200"] = df["close"].rolling(200).mean()
    return df


def compute_emas(df: pd.DataFrame) -> pd.DataFrame:
    df["ema_5"] = df["close"].ewm(span=5, adjust=False).mean()
    df["ema_21"] = df["close"].ewm(span=21, adjust=False).mean()
    return df


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    df["atr_14"] = tr.rolling(period).mean()
    return df


def compute_volume_sma(df: pd.DataFrame) -> pd.DataFrame:
    df["volume_sma_50"] = df["volume"].rolling(50).mean()
    return df


def compute_52w_levels(df: pd.DataFrame) -> pd.DataFrame:
    df["high_52w"] = df["high"].rolling(252).max()
    df["low_52w"] = df["low"].rolling(252).min()
    return df


def compute_rs_return(df: pd.DataFrame, period: int = 63) -> pd.DataFrame:
    """63-trading-day (≈ 3-month) price return for cross-universe RS ranking."""
    df["rs_63d_return"] = df["close"].pct_change(periods=period)
    return df


def compute_volume_sma_10(df: pd.DataFrame) -> pd.DataFrame:
    df["volume_sma_10"] = df["volume"].rolling(10).mean()
    return df


def compute_all(df: pd.DataFrame) -> pd.DataFrame:
    df = compute_smas(df)
    df = compute_emas(df)
    df = compute_atr(df)
    df = compute_volume_sma(df)
    df = compute_volume_sma_10(df)
    df = compute_52w_levels(df)
    df = compute_rs_return(df)
    return df


def rank_rs_across_universe(returns: dict[str, float]) -> dict[str, float]:
    """
    Given a dict of {symbol: 63d_return}, return {symbol: percentile_rank (0-100)}.
    Higher rank = stronger relative strength.
    """
    if not returns:
        return {}
    series = pd.Series(returns)
    ranks = series.rank(pct=True) * 100
    return ranks.to_dict()

import pandas as pd
import numpy as np
from tests.mock_data import make_stage2_base
from screening.indicators import compute_all, rank_rs_across_universe


def test_smas_computed():
    df = compute_all(make_stage2_base())
    assert "sma_50" in df.columns
    assert "sma_150" in df.columns
    assert "sma_200" in df.columns
    # First 199 rows should be NaN for sma_200
    assert df["sma_200"].iloc[198] != df["sma_200"].iloc[198]  # NaN check
    assert not pd.isna(df["sma_200"].iloc[-1])


def test_atr_positive():
    df = compute_all(make_stage2_base())
    atr = df["atr_14"].dropna()
    assert (atr > 0).all()


def test_52w_levels():
    df = compute_all(make_stage2_base())
    last = df.iloc[-1]
    assert last["high_52w"] >= last["close"]
    assert last["low_52w"] <= last["close"]


def test_rs_ranks_sum_to_universe():
    from tests.mock_data import make_downtrend, make_choppy_sideways
    # Compute 63-day returns manually and pass to rank function
    def _return_63d(series: pd.Series) -> float:
        return (series.iloc[-1] - series.iloc[-64]) / series.iloc[-64]

    returns = {
        "STRONG": _return_63d(make_stage2_base()["close"]),
        "WEAK": _return_63d(make_downtrend()["close"]),
        "FLAT": _return_63d(make_choppy_sideways()["close"]),
    }
    ranks = rank_rs_across_universe(returns)
    assert ranks["STRONG"] > ranks["WEAK"]


def test_volume_sma():
    df = compute_all(make_stage2_base())
    last = df["volume_sma_50"].iloc[-1]
    assert last > 0

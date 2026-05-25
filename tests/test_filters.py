import pandas as pd
from tests.mock_data import make_stage2_base, make_downtrend, make_choppy_sideways
from screening.indicators import compute_all
from screening.filters import (
    passes_stage2_trend,
    passes_sma200_trend,
    passes_52w_proximity,
    passes_rs_rank,
)
from screening.base_detection import find_base


def _prep(make_fn):
    df = compute_all(make_fn())
    return df


def test_stage2_passes_for_uptrend():
    df = _prep(make_stage2_base)
    last = df.iloc[-1]
    passes, failures = passes_stage2_trend(last)
    assert passes, f"Expected Stage 2 pass, failed: {failures}"


def test_stage2_fails_for_downtrend():
    df = _prep(make_downtrend)
    last = df.iloc[-1]
    passes, _ = passes_stage2_trend(last)
    assert not passes


def test_sma200_trending_up():
    df = _prep(make_stage2_base)
    assert passes_sma200_trend(df, len(df) - 1, weeks=4)


def test_sma200_not_trending_for_downtrend():
    df = _prep(make_downtrend)
    assert not passes_sma200_trend(df, len(df) - 1, weeks=4)


def test_52w_proximity_passes():
    df = _prep(make_stage2_base)
    last = df.iloc[-1]
    assert passes_52w_proximity(last["close"], last["high_52w"], max_below_pct=0.25)


def test_rs_rank_threshold():
    assert passes_rs_rank(75.0, min_percentile=70.0)
    assert not passes_rs_rank(65.0, min_percentile=70.0)


def test_base_detected_for_stage2():
    df = _prep(make_stage2_base)
    result = find_base(df, len(df) - 1)
    assert result is not None, "Expected a base to be detected"
    assert result["base_depth_pct"] <= 0.35
    assert result["base_length_weeks"] >= 4
    assert result["near_pivot"]


def test_no_base_for_downtrend():
    df = _prep(make_downtrend)
    result = find_base(df, len(df) - 1)
    assert result is None, "Should not detect a valid base in a downtrend"

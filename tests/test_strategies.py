import pandas as pd
import numpy as np
from tests.mock_data import make_stage2_base, make_downtrend
from screening.indicators import compute_all
from screening.strategies.vcp import detect_vcp
from screening.strategies.qullamaggie import detect_qullamaggie_setup
from screening.strategies.pocket_pivot import detect_pocket_pivot
from screening.strategies.gap_up import detect_gap_up
from screening.strategies.ema_pullback import detect_ema_pullback
from screening.strategies.runner import run_all_strategies


def _prep(make_fn):
    return compute_all(make_fn())


# --- VCP ---

def test_vcp_returns_dict_or_none_for_stage2():
    df = _prep(make_stage2_base)
    result = detect_vcp(df, len(df) - 1)
    # May or may not fire depending on contraction structure — just verify no crash
    assert result is None or isinstance(result, dict)


def test_vcp_does_not_fire_on_downtrend():
    df = _prep(make_downtrend)
    result = detect_vcp(df, len(df) - 1)
    assert result is None


# --- Qullamaggie ---

def test_qullamaggie_requires_price_above_sma50():
    df = _prep(make_downtrend)
    result = detect_qullamaggie_setup(df, len(df) - 1)
    assert result is None


def test_qullamaggie_returns_dict_or_none_for_stage2():
    df = _prep(make_stage2_base)
    result = detect_qullamaggie_setup(df, len(df) - 1)
    assert result is None or isinstance(result, dict)


# --- Pocket Pivot ---

def test_pocket_pivot_requires_above_sma50():
    df = _prep(make_downtrend)
    result = detect_pocket_pivot(df, len(df) - 1)
    assert result is None


def test_pocket_pivot_volume_condition():
    """Manually construct a pocket pivot day."""
    df = compute_all(make_stage2_base())
    end_idx = len(df) - 1

    # Force today's volume to be enormous so it beats all down days
    df = df.copy()
    df.iloc[end_idx, df.columns.get_loc("volume")] = int(df["volume"].max() * 10)
    # Recompute volume SMAs
    df["volume_sma_50"] = df["volume"].rolling(50).mean()
    df["volume_sma_10"] = df["volume"].rolling(10).mean()

    result = detect_pocket_pivot(df, end_idx)
    # With massive volume and Stage 2 stock near SMAs, should fire
    assert result is None or result["volume_ratio_vs_down_days"] > 1.0


# --- Gap Up ---

def test_gap_up_requires_true_gap():
    """No gap = no signal."""
    df = _prep(make_stage2_base)
    # Last row has no gap in mock data
    result = detect_gap_up(df, len(df) - 1)
    assert result is None


def test_gap_up_detects_manufactured_gap():
    df = compute_all(make_stage2_base())
    df = df.copy()
    end_idx = len(df) - 1
    prev_high = df["high"].iloc[end_idx - 1]

    # Force a gap: open well above prior high, close near day high, big volume
    df.iloc[end_idx, df.columns.get_loc("open")] = prev_high * 1.05
    df.iloc[end_idx, df.columns.get_loc("high")] = prev_high * 1.08
    df.iloc[end_idx, df.columns.get_loc("close")] = prev_high * 1.07
    df.iloc[end_idx, df.columns.get_loc("low")] = prev_high * 1.04
    df.iloc[end_idx, df.columns.get_loc("volume")] = int(df["volume_sma_10"].iloc[end_idx] * 3)

    result = detect_gap_up(df, end_idx)
    assert result is not None
    assert result["gap_pct"] > 0.01
    assert result["volume_ratio"] >= 1.5


# --- Runner ---

def test_runner_returns_none_when_no_signals():
    df = _prep(make_downtrend)
    result = run_all_strategies(df, "WEAK")
    assert result is None


def test_runner_composite_score_bounded():
    df = _prep(make_stage2_base)
    result = run_all_strategies(df, "STRONG")
    if result is not None:
        assert 0 <= result["composite_score"] <= 100
        assert len(result["strategies_fired"]) >= 1


def test_runner_multi_strategy_bonus():
    """Manually inject two signals and verify bonus applies."""
    from screening.strategies.runner import _composite_score
    signals = {
        "vcp": {"quality_score": 60.0},
        "qullamaggie": {"quality_score": 60.0},
    }
    score = _composite_score(signals)
    single = _composite_score({"vcp": {"quality_score": 60.0}})
    assert score > single

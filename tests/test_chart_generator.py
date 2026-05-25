"""
Tests for charts/generator.py using synthetic OHLCV data.
No real data or API calls required.
"""
import numpy as np
import pandas as pd
import pytest

from charts.generator import generate_chart
from screening.indicators import compute_all


# ---------------------------------------------------------------------------
# Mock data factory
# ---------------------------------------------------------------------------

def _make_ohlcv(n: int = 300, seed: int = 42) -> pd.DataFrame:
    """Generate n business days of synthetic OHLCV data with a mild uptrend."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end="2026-05-23", periods=n)

    price = 50.0
    closes = []
    for i in range(n):
        volatility = 0.008 if i >= n - 30 else 0.018
        drift = 0.0 if i >= n - 30 else 0.0005
        price = max(price * (1 + rng.normal(drift, volatility)), 1.0)
        closes.append(price)

    closes = np.array(closes)
    highs = closes * (1 + rng.uniform(0.003, 0.015, n))
    lows = closes * (1 - rng.uniform(0.003, 0.015, n))
    opens = np.clip(closes * (1 + rng.normal(0, 0.005, n)), lows, highs)
    volume = rng.uniform(300_000, 700_000, n)
    volume[-30:] *= rng.uniform(0.4, 0.7, 30)

    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volume},
        index=dates,
    )


# ---------------------------------------------------------------------------
# Signal factories — mirror the shape run_all_strategies() returns
# ---------------------------------------------------------------------------

def _sig(strategy: str, df: pd.DataFrame, extra: dict | None = None) -> dict:
    """Base signal wrapper for a single strategy."""
    close = float(df["close"].iloc[-1])
    low = float(df["low"].iloc[-1])
    high = float(df["high"].iloc[-1])
    base = {
        "symbol": "MOCK",
        "strategies_fired": [strategy],
        "n_strategies": 1,
        "composite_score": 70.0,
        "alert_type": strategy,
        "pivot_price": close * 1.01,
        "signals": {strategy: {"quality_score": 70.0, **(extra or {})}},
    }
    return base


def _vcp_signal(df):
    close = float(df["close"].iloc[-1])
    return _sig("vcp", df, {
        "strategy": "vcp",
        "pivot_price": close * 1.01,
        "n_contractions": 3,
        "contraction_depths": [0.12, 0.08, 0.05],
        "volume_declining": True,
    })


def _qullamaggie_signal(df):
    close = float(df["close"].iloc[-1])
    return _sig("qullamaggie", df, {
        "strategy": "qullamaggie",
        "pivot_price": close * 1.02,
        "base_low": close * 0.90,
        "base_days": 18,
        "prior_move_pct": 0.45,
        "volume_drying": True,
    })


def _ema_pullback_signal(df):
    high = float(df["high"].iloc[-1])
    return _sig("ema_pullback", df, {
        "strategy": "ema_pullback",
        "entry_trigger": high,
        "inside_day_high": high,
        "inside_day_low": float(df["low"].iloc[-1]),
        "surge_move_pct": 0.12,
        "surge_days": 4,
        "surge_volume_ratio": 1.8,
        "days_since_surge": 3,
    })


def _gap_up_signal(df):
    low = float(df["low"].iloc[-1])
    high = float(df["high"].iloc[-1])
    return _sig("gap_up", df, {
        "strategy": "gap_up",
        "gap_pct": 0.03,
        "volume_ratio": 2.1,
        "gap_day_low": low,
        "gap_day_high": high,
    })


def _pocket_pivot_signal(df):
    close = float(df["close"].iloc[-1])
    vol = float(df["volume"].iloc[-1])
    return _sig("pocket_pivot", df, {
        "strategy": "pocket_pivot",
        "reference_sma": "sma_10",
        "reference_sma_value": close * 0.97,
        "crosses_over": True,
        "volume_ratio_vs_down_days": 1.8,
        "volume_ratio_vs_50d_avg": 1.4,
        "max_down_day_volume": vol * 0.7,
        "today_volume": vol,
    })


def _multi_signal(df):
    close = float(df["close"].iloc[-1])
    vol = float(df["volume"].iloc[-1])
    return {
        "symbol": "MOCK",
        "strategies_fired": ["vcp", "pocket_pivot"],
        "n_strategies": 2,
        "composite_score": 85.0,
        "alert_type": "VCP Setup + Pocket Pivot",
        "pivot_price": close * 1.01,
        "signals": {
            "vcp": {
                "strategy": "vcp", "pivot_price": close * 1.01,
                "n_contractions": 3, "volume_declining": True, "quality_score": 72.0,
            },
            "pocket_pivot": {
                "strategy": "pocket_pivot",
                "reference_sma": "sma_10",
                "reference_sma_value": close * 0.97,
                "crosses_over": True,
                "volume_ratio_vs_down_days": 1.8,
                "max_down_day_volume": vol * 0.7,
                "today_volume": vol,
                "quality_score": 80.0,
            },
        },
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def df():
    raw = _make_ohlcv(300)
    return compute_all(raw)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestEma21InIndicators:
    def test_ema_21_computed(self, df):
        assert "ema_21" in df.columns
        assert not df["ema_21"].isna().all()


class TestSingleStrategyCharts:
    def test_vcp_chart_created(self, df, tmp_path):
        out = generate_chart(df, _vcp_signal(df), "MOCK", output_dir=tmp_path)
        assert out.exists() and out.stat().st_size > 50_000

    def test_qullamaggie_chart_created(self, df, tmp_path):
        out = generate_chart(df, _qullamaggie_signal(df), "MOCK", output_dir=tmp_path)
        assert out.exists() and out.stat().st_size > 50_000

    def test_ema_pullback_chart_created(self, df, tmp_path):
        out = generate_chart(df, _ema_pullback_signal(df), "MOCK", output_dir=tmp_path)
        assert out.exists() and out.stat().st_size > 50_000

    def test_gap_up_chart_created(self, df, tmp_path):
        out = generate_chart(df, _gap_up_signal(df), "MOCK", output_dir=tmp_path)
        assert out.exists() and out.stat().st_size > 50_000

    def test_pocket_pivot_chart_created(self, df, tmp_path):
        out = generate_chart(df, _pocket_pivot_signal(df), "MOCK", output_dir=tmp_path)
        assert out.exists() and out.stat().st_size > 50_000


class TestMultiStrategyChart:
    def test_multi_strategy_creates_file(self, df, tmp_path):
        out = generate_chart(df, _multi_signal(df), "MOCK", output_dir=tmp_path)
        assert out.exists()

    def test_multi_chart_wider_than_single(self, df, tmp_path):
        single_path = tmp_path / "single"
        single_path.mkdir()
        multi_path = tmp_path / "multi"
        multi_path.mkdir()

        single_out = generate_chart(df, _vcp_signal(df), "MOCK", output_dir=single_path)
        multi_out = generate_chart(df, _multi_signal(df), "MOCK", output_dir=multi_path)

        # Multi-chart should be significantly larger in file size
        assert multi_out.stat().st_size > single_out.stat().st_size * 1.5

    def test_filename_contains_symbol_and_date(self, df, tmp_path):
        out = generate_chart(df, _vcp_signal(df), "AAPL", output_dir=tmp_path)
        assert "AAPL" in out.name
        assert "2026" in out.name


class TestEdgeCases:
    def test_missing_ma_columns_do_not_crash(self, df, tmp_path):
        df_partial = df.drop(columns=["sma_150", "sma_200", "ema_21"], errors="ignore")
        out = generate_chart(df_partial, _vcp_signal(df), "MOCK", output_dir=tmp_path)
        assert out.exists()

    def test_lookback_override(self, df, tmp_path):
        out = generate_chart(df, _vcp_signal(df), "MOCK", output_dir=tmp_path, lookback_days=40)
        assert out.exists()

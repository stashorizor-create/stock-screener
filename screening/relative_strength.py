import pandas as pd


def compute_universe_rs_ranks(
    closes: dict[str, pd.Series],
    as_of_date: pd.Timestamp,
    period: int = 63,
) -> dict[str, float]:
    """
    Compute RS percentile rank (0-100) for all symbols as of a given date.

    closes: {symbol: pd.Series indexed by date}
    Returns: {symbol: percentile_rank}
    """
    returns: dict[str, float] = {}

    for symbol, series in closes.items():
        try:
            series = series.sort_index()
            if as_of_date not in series.index:
                continue
            end_pos = series.index.get_loc(as_of_date)
            if end_pos < period:
                continue
            end_price = series.iloc[end_pos]
            start_price = series.iloc[end_pos - period]
            if start_price <= 0:
                continue
            returns[symbol] = (end_price - start_price) / start_price
        except (KeyError, IndexError):
            continue

    if not returns:
        return {}

    series = pd.Series(returns)
    ranks = series.rank(pct=True) * 100
    return ranks.to_dict()


def rs_line_making_new_highs(
    symbol_close: pd.Series,
    benchmark_close: pd.Series,
    lookback_days: int = 63,
) -> bool:
    """
    Check if the RS line (symbol / benchmark ratio) is at a new high
    over the past lookback_days. Preferred for sorting top candidates.
    """
    if len(symbol_close) < lookback_days or len(benchmark_close) < lookback_days:
        return False

    rs_line = symbol_close / benchmark_close
    current_rs = rs_line.iloc[-1]
    prior_high = rs_line.iloc[-lookback_days:-1].max()

    return current_rs >= prior_high

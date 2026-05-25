import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
from datetime import date, timedelta
from data.ingestor import client as borsdata
from screening.indicators import compute_all
from screening.filters import passes_stage2_trend, passes_sma200_trend, passes_52w_proximity

from_date = date.today() - timedelta(days=420)
instruments = borsdata.get_instruments()
stocks = instruments[(instruments["instrument"] == 0) & instruments["marketId"].isin([1, 2, 3])].head(20)
print(f"Stocks to check: {len(stocks)}")

for _, row in stocks.iterrows():
    ins_id = int(row["insId"])
    sym = str(row.get("ticker") or f"BD{ins_id}")
    try:
        df = borsdata.get_ohlcv(ins_id, from_date=from_date)
        if df.empty or len(df) < 210:
            print(f"{sym:<12} rows={len(df)}  SKIP (insufficient history)")
            continue
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        df = compute_all(df)
        last = df.iloc[-1]
        daily_value = float(last["volume_sma_50"]) * float(last["close"])
        liq   = daily_value >= 2_000_000
        s2, fails = passes_stage2_trend(last)
        sma200 = passes_sma200_trend(df, len(df) - 1)
        prox   = passes_52w_proximity(float(last["close"]), float(last["high_52w"]))
        ok = s2 and sma200 and prox and liq
        status = "PASS" if ok else f"fail  s2={s2} fails={fails} sma200={sma200} prox={prox} liq={liq}"
        print(f"{sym:<12} val={daily_value/1e6:.1f}M SEK  close={last['close']:.1f}  {status}")
    except Exception as exc:
        print(f"{sym:<12} ERROR: {exc}")

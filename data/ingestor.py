"""
Borsdata Pro+ API client.
Stub — ready to activate once BORSDATA_API_KEY is set.
API docs: https://github.com/Borsdata-Sweden/API
Rate limit: 100 calls / 10 seconds
"""
import time
import logging
from datetime import date, timedelta
from typing import Any

import requests
import pandas as pd

from config.settings import settings

logger = logging.getLogger(__name__)

RATE_LIMIT_CALLS = 100
RATE_LIMIT_WINDOW = 10  # seconds


class BorsdataClient:
    def __init__(self):
        self.api_key = settings.BORSDATA_API_KEY
        self.base_url = settings.BORSDATA_BASE_URL
        self.session = requests.Session()
        self._call_times: list[float] = []

    def _throttle(self):
        """Enforce 100 calls / 10s rate limit."""
        now = time.monotonic()
        self._call_times = [t for t in self._call_times if now - t < RATE_LIMIT_WINDOW]
        if len(self._call_times) >= RATE_LIMIT_CALLS:
            sleep_for = RATE_LIMIT_WINDOW - (now - self._call_times[0]) + 0.05
            if sleep_for > 0:
                time.sleep(sleep_for)
        self._call_times.append(time.monotonic())

    def _get(self, endpoint: str, params: dict | None = None) -> Any:
        self._throttle()
        params = params or {}
        params["authKey"] = self.api_key
        url = f"{self.base_url}{endpoint}"
        resp = self.session.get(url, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    # -------------------------------------------------------------------------
    # Universe
    # -------------------------------------------------------------------------

    def get_instruments(self) -> pd.DataFrame:
        """All Nordic instruments (stocks, warrants, etc)."""
        data = self._get("/instruments")
        instruments = data.get("instruments", [])
        return pd.DataFrame(instruments)

    def get_instruments_global(self) -> pd.DataFrame:
        """All global instruments including US stocks."""
        data = self._get("/instruments/global")
        instruments = data.get("instruments", [])
        return pd.DataFrame(instruments)

    def get_markets(self) -> pd.DataFrame:
        data = self._get("/markets")
        return pd.DataFrame(data.get("markets", []))

    # -------------------------------------------------------------------------
    # OHLCV
    # -------------------------------------------------------------------------

    def get_ohlcv(
        self,
        instrument_id: int,
        from_date: date | None = None,
        to_date: date | None = None,
        max_count: int = 400,
    ) -> pd.DataFrame:
        """
        EOD OHLCV for a single instrument.
        Returns DataFrame with columns: date, open, high, low, close, volume.
        """
        params: dict = {"maxCount": max_count}
        if from_date:
            params["from"] = from_date.isoformat()
        if to_date:
            params["to"] = to_date.isoformat()

        data = self._get(f"/instruments/{instrument_id}/stockprices", params=params)
        prices = data.get("stockPricesList", [])

        if not prices:
            return pd.DataFrame()

        df = pd.DataFrame(prices)
        df = df.rename(columns={
            "d": "date",
            "o": "open",
            "h": "high",
            "l": "low",
            "c": "close",
            "v": "volume",
        })
        df["date"] = pd.to_datetime(df["date"]).dt.date
        df = df.sort_values("date").reset_index(drop=True)
        return df

    def get_ohlcv_bulk(
        self,
        instrument_ids: list[int],
        from_date: date | None = None,
    ) -> dict[int, pd.DataFrame]:
        """
        Fetch OHLCV for multiple instruments.
        Returns {instrument_id: DataFrame}.
        """
        results: dict[int, pd.DataFrame] = {}
        for i, iid in enumerate(instrument_ids):
            try:
                df = self.get_ohlcv(iid, from_date=from_date)
                if not df.empty:
                    results[iid] = df
            except Exception as exc:
                logger.warning("OHLCV fetch failed for instrument %s: %s", iid, exc)
            if i % 50 == 0 and i > 0:
                logger.info("Fetched %d / %d instruments", i, len(instrument_ids))
        return results

    # -------------------------------------------------------------------------
    # Corporate actions
    # -------------------------------------------------------------------------

    def get_splits(self, instrument_id: int) -> pd.DataFrame:
        data = self._get(f"/instruments/{instrument_id}/splits")
        return pd.DataFrame(data.get("splits", []))

    def get_dividends(self, instrument_id: int) -> pd.DataFrame:
        data = self._get(f"/instruments/{instrument_id}/dividends")
        return pd.DataFrame(data.get("dividends", []))


# Module-level singleton — import this in other modules
client = BorsdataClient()

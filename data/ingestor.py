"""
Borsdata Pro+ API client.
API docs: https://github.com/Borsdata-Sweden/API
Rate limit: 100 calls / 10 seconds
"""
import time
import logging
from datetime import date, datetime, timedelta
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

    # -------------------------------------------------------------------------
    # Fundamentals
    # -------------------------------------------------------------------------

    def get_reports_quarter(self, instrument_id: int, max_count: int = 8) -> list[dict]:
        """
        Return up to max_count quarterly reports, newest first.
        Each dict has: year, period, earnings_Per_Share, net_Sales, revenues, report_Date
        """
        data = self._get(
            f"/instruments/{instrument_id}/reports/quarter",
            params={"maxCount": max_count},
        )
        reports = data.get("reports", [])
        # Sort newest first (year desc, period desc)
        reports.sort(key=lambda r: (r.get("year", 0), r.get("period", 0)), reverse=True)
        return reports

    def get_fundamentals(self, instrument_id: int) -> dict:
        """
        Compute EPS and revenue growth from the last 8 quarterly reports.

        Returns:
            eps_yoy, eps_qoq, revenue_yoy, revenue_qoq  — decimal growth rates
            earnings_days_out                            — estimated days to next report
        All values are None if data is unavailable.
        """
        try:
            reports = self.get_reports_quarter(instrument_id, max_count=8)
        except Exception as exc:
            logger.warning("Fundamentals fetch failed for instrument %s: %s", instrument_id, exc)
            return {}

        if len(reports) < 2:
            return {}

        def _safe_float(r: dict, key: str) -> float | None:
            v = r.get(key)
            return float(v) if v is not None else None

        latest  = reports[0]
        prev_q  = reports[1] if len(reports) > 1 else None
        year_ago = reports[4] if len(reports) > 4 else None

        eps_l   = _safe_float(latest,   "earnings_Per_Share")
        rev_l   = _safe_float(latest,   "net_Sales")
        eps_p   = _safe_float(prev_q,   "earnings_Per_Share") if prev_q  else None
        rev_p   = _safe_float(prev_q,   "net_Sales")          if prev_q  else None
        eps_ya  = _safe_float(year_ago, "earnings_Per_Share") if year_ago else None
        rev_ya  = _safe_float(year_ago, "net_Sales")          if year_ago else None

        def _growth(new, old) -> float | None:
            if new is None or old is None or old == 0:
                return None
            return round((new - old) / abs(old), 4)

        # Estimate next earnings date (~91 days after last report publication)
        earnings_days_out = None
        try:
            rd = latest.get("report_Date", "")
            if rd:
                last_pub = datetime.fromisoformat(rd.replace("Z", "")).date()
                next_pub = last_pub + timedelta(days=91)
                days = (next_pub - date.today()).days
                earnings_days_out = max(0, days) if days < 180 else None
        except Exception:
            pass

        return {
            "eps_qoq":          _growth(eps_l, eps_p),
            "eps_yoy":          _growth(eps_l, eps_ya),
            "revenue_qoq":      _growth(rev_l, rev_p),
            "revenue_yoy":      _growth(rev_l, rev_ya),
            "earnings_days_out": earnings_days_out,
        }


# Module-level singleton — import this in other modules
client = BorsdataClient()

from dataclasses import dataclass


@dataclass
class ExchangeConfig:
    name: str
    country: str
    currency: str
    min_avg_volume: float       # in local currency (value) or shares
    volume_unit: str            # "value" (NOK/SEK) or "shares"
    min_price: float
    timezone: str
    market_close_hour: int      # local time


EXCHANGES: dict[str, ExchangeConfig] = {
    # Liquidity = price × 10-day avg volume ≥ min_avg_volume (local currency value)
    "OSL": ExchangeConfig(
        name="Oslo Børs",
        country="NO",
        currency="NOK",
        min_avg_volume=5_000_000,   # NOK value/day
        volume_unit="value",
        min_price=10.0,
        timezone="Europe/Oslo",
        market_close_hour=17,
    ),
    "STO": ExchangeConfig(
        name="Nasdaq Stockholm",
        country="SE",
        currency="SEK",
        min_avg_volume=5_000_000,   # SEK value/day
        volume_unit="value",
        min_price=10.0,
        timezone="Europe/Stockholm",
        market_close_hour=17,
    ),
    "CPH": ExchangeConfig(
        name="Nasdaq Copenhagen",
        country="DK",
        currency="DKK",
        min_avg_volume=5_000_000,   # DKK value/day
        volume_unit="value",
        min_price=10.0,
        timezone="Europe/Copenhagen",
        market_close_hour=17,
    ),
    "HEL": ExchangeConfig(
        name="Nasdaq Helsinki",
        country="FI",
        currency="EUR",
        min_avg_volume=5_000_000,   # EUR value/day
        volume_unit="value",
        min_price=5.0,
        timezone="Europe/Helsinki",
        market_close_hour=18,
    ),
    # ---- US ----
    "NYSE": ExchangeConfig(
        name="New York Stock Exchange",
        country="US",
        currency="USD",
        min_avg_volume=10_000_000,  # USD value/day
        volume_unit="value",
        min_price=10.0,
        timezone="America/New_York",
        market_close_hour=16,
    ),
    "NASDAQ": ExchangeConfig(
        name="Nasdaq US",
        country="US",
        currency="USD",
        min_avg_volume=10_000_000,  # USD value/day
        volume_unit="value",
        min_price=10.0,
        timezone="America/New_York",
        market_close_hour=16,
    ),
}

EXCLUDED_INSTRUMENT_TYPES = {"warrant", "etf", "reit", "preferred", "certificate", "fund"}

NORDIC_EXCHANGES   = {"OSL", "STO", "CPH", "HEL"}
US_EXCHANGES       = {"NYSE", "NASDAQ"}
ALL_EXCHANGES      = set(EXCHANGES.keys())

# Borsdata-internal market IDs that are only available via get_instruments()
# (Nordic endpoint). Everything else comes from get_instruments_global().
NORDIC_MARKET_IDS: frozenset[int] = frozenset({
    1, 2, 3, 4, 5, 6,           # Stockholm
    9, 10, 11, 12, 27, 78,      # Oslo
    14, 15, 16, 17, 30,         # Helsinki
    20, 21, 22, 23, 48,         # Copenhagen
})

# Borsdata marketId → our exchange code (indices excluded).
# Single source of truth — imported by run.py (universe build) and the forward-test
# evaluator (resolving symbol+exchange → Borsdata insId).
MARKET_ID_TO_EXCHANGE: dict[int, str] = {
    # Sweden — Stockholm
    1: "STO", 2: "STO", 3: "STO", 4: "STO", 5: "STO", 6: "STO",
    # Norway — Oslo
    9: "OSL", 10: "OSL", 11: "OSL", 12: "OSL", 27: "OSL", 78: "OSL",
    # Finland — Helsinki
    14: "HEL", 15: "HEL", 16: "HEL", 17: "HEL", 30: "HEL",
    # Denmark — Copenhagen
    20: "CPH", 21: "CPH", 22: "CPH", 23: "CPH", 48: "CPH",
    # US
    32: "NYSE", 33: "NASDAQ",
}

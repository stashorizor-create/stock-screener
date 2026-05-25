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
        min_price=10.0,             # no penny stocks
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

NORDIC_EXCHANGES = {"OSL", "STO", "CPH", "HEL"}
US_EXCHANGES = {"NYSE", "NASDAQ"}
ALL_EXCHANGES = set(EXCHANGES.keys())

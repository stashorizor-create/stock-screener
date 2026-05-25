import logging
from datetime import datetime, date

import pandas as pd
from sqlalchemy.orm import Session

from config.universe_config import EXCHANGES, EXCLUDED_INSTRUMENT_TYPES
from database.models import Universe, OHLCV, SessionLocal

logger = logging.getLogger(__name__)


BORSDATA_MARKET_TO_EXCHANGE = {
    "Sweden": "STO",
    "Norway": "OSL",
    "Denmark": "CPH",
    "Finland": "HEL",
    "NYSE": "NYSE",
    "Nasdaq": "NASDAQ",
    "Nasdaq US": "NASDAQ",
}


def sync_universe(instruments_df: pd.DataFrame) -> int:
    """
    Upsert instruments from Borsdata into the universe table.
    Returns number of active instruments after sync.
    """
    if instruments_df.empty:
        logger.warning("No instruments to sync")
        return 0

    added = 0
    updated = 0

    with SessionLocal() as session:
        for _, row in instruments_df.iterrows():
            instrument_type = str(row.get("instrument", "")).lower()
            if instrument_type in EXCLUDED_INSTRUMENT_TYPES:
                continue

            market = str(row.get("marketPlace", row.get("market", "")))
            exchange = BORSDATA_MARKET_TO_EXCHANGE.get(market)
            if exchange is None:
                continue

            borsdata_id = int(row["insId"])
            symbol = str(row.get("ticker", row.get("symbol", f"BD{borsdata_id}")))
            name = str(row.get("name", ""))
            currency = str(row.get("currency", EXCHANGES[exchange].currency))

            existing = session.query(Universe).filter_by(borsdata_id=borsdata_id).first()
            if existing:
                existing.symbol = symbol
                existing.name = name
                existing.exchange = exchange
                existing.currency = currency
                existing.is_active = True
                existing.last_updated = datetime.utcnow()
                updated += 1
            else:
                session.add(Universe(
                    symbol=symbol,
                    name=name,
                    exchange=exchange,
                    currency=currency,
                    borsdata_id=borsdata_id,
                    instrument_type=instrument_type,
                    is_active=True,
                    last_updated=datetime.utcnow(),
                ))
                added += 1

        session.commit()

    total = added + updated
    logger.info("Universe sync: %d added, %d updated, %d total", added, updated, total)
    return total


def update_liquidity_flags(session: Session, as_of_date: date) -> None:
    """
    Compute 50-day average volume for each symbol and flag those meeting
    the exchange-specific minimum. Runs after OHLCV is loaded.
    """
    instruments = session.query(Universe).filter_by(is_active=True).all()

    for inst in instruments:
        cfg = EXCHANGES.get(inst.exchange)
        if cfg is None:
            continue

        recent_rows = (
            session.query(OHLCV)
            .filter(OHLCV.symbol == inst.symbol)
            .order_by(OHLCV.date.desc())
            .limit(50)
            .all()
        )

        if len(recent_rows) < 20:
            inst.liquidity_pass = False
            continue

        closes = [r.close for r in recent_rows if r.close]
        volumes = [r.volume for r in recent_rows if r.volume]

        if not volumes:
            inst.liquidity_pass = False
            continue

        avg_vol = sum(volumes) / len(volumes)
        avg_close = sum(closes) / len(closes) if closes else 1.0

        if cfg.volume_unit == "value":
            avg_daily_value = avg_vol * avg_close
            passes = avg_daily_value >= cfg.min_avg_volume
        else:
            passes = avg_vol >= cfg.min_avg_volume

        inst.avg_volume_50d = avg_vol
        inst.liquidity_pass = passes and (avg_close >= cfg.min_price)
        inst.last_updated = datetime.utcnow()

    session.commit()
    logger.info("Liquidity flags updated for %d instruments", len(instruments))


def get_active_liquid_symbols(session: Session, exchange: str | None = None) -> list[Universe]:
    query = session.query(Universe).filter_by(is_active=True, liquidity_pass=True)
    if exchange:
        query = query.filter_by(exchange=exchange)
    return query.all()

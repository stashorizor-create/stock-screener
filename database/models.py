from datetime import date, datetime
from sqlalchemy import (
    Boolean, Column, Date, DateTime, Float, ForeignKey,
    Integer, String, Text, UniqueConstraint, create_engine,
)
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from config.settings import settings


class Base(DeclarativeBase):
    pass


_db_url = settings.DATABASE_URL.replace("postgres://", "postgresql://", 1)
engine = create_engine(
    _db_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


class Universe(Base):
    __tablename__ = "universe"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), unique=True, nullable=False)
    name = Column(String(200))
    exchange = Column(String(10), nullable=False)       # OSL, STO, CPH, HEL, NYSE, NASDAQ
    currency = Column(String(5))
    borsdata_id = Column(Integer, unique=True)          # Borsdata instrument ID
    instrument_type = Column(String(30))                # stock, warrant, etf, etc
    is_active = Column(Boolean, default=True)
    avg_volume_50d = Column(Float)
    liquidity_pass = Column(Boolean, default=False)
    last_updated = Column(DateTime)


class OHLCV(Base):
    __tablename__ = "ohlcv"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), ForeignKey("universe.symbol"), nullable=False)
    date = Column(Date, nullable=False)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(Float)
    adj_close = Column(Float)   # split/dividend adjusted

    __table_args__ = (UniqueConstraint("symbol", "date", name="uq_ohlcv_symbol_date"),)


class Indicators(Base):
    __tablename__ = "indicators"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), ForeignKey("universe.symbol"), nullable=False)
    date = Column(Date, nullable=False)
    sma_50 = Column(Float)
    sma_150 = Column(Float)
    sma_200 = Column(Float)
    atr_14 = Column(Float)
    volume_sma_50 = Column(Float)
    high_52w = Column(Float)
    low_52w = Column(Float)
    rs_63d_return = Column(Float)   # raw 63-day return, used for RS ranking
    rs_rank = Column(Float)          # percentile rank within universe (0-100)

    __table_args__ = (UniqueConstraint("symbol", "date", name="uq_indicators_symbol_date"),)


class Candidate(Base):
    __tablename__ = "candidates"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), ForeignKey("universe.symbol"), nullable=False)
    date = Column(Date, nullable=False)
    stage2_confirmed = Column(Boolean)
    near_pivot = Column(Boolean)
    base_length_weeks = Column(Float)
    base_depth_pct = Column(Float)
    pivot_price = Column(Float)
    base_low = Column(Float)
    atr_contracting = Column(Boolean)
    volume_drying = Column(Boolean)
    rs_rank = Column(Float)
    technical_score = Column(Float)   # composite 0-100
    chart_image_path = Column(String(300))

    __table_args__ = (UniqueConstraint("symbol", "date", name="uq_candidates_symbol_date"),)


class Enrichment(Base):
    __tablename__ = "enrichment"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), ForeignKey("universe.symbol"), nullable=False)
    date = Column(Date, nullable=False)
    insider_buy_days_ago = Column(Integer)
    insider_buy_value = Column(Float)
    news_sentiment = Column(Float)      # -1.0 to 1.0
    news_headline = Column(Text)
    google_trends_acceleration = Column(Float)
    stocktwits_mention_velocity = Column(Float)
    sector_theme = Column(String(100))
    earnings_days_out = Column(Integer)

    __table_args__ = (UniqueConstraint("symbol", "date", name="uq_enrichment_symbol_date"),)


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), ForeignKey("universe.symbol"), nullable=False)
    date = Column(Date, nullable=False)
    entry_price = Column(Float)
    stop_price = Column(Float)
    target_price = Column(Float)
    risk_reward = Column(Float)
    composite_score = Column(Float)     # Python scorer output (0-100)
    confidence_score = Column(Float)    # AI-blended confidence (0-100)
    pattern_quality = Column(Integer)   # 1-10 from Claude vision
    ai_narrative = Column(Text)
    chart_image_path = Column(String(300))
    sent_at = Column(DateTime)
    # Rich signal fields added in migration
    rs_rank = Column(Float)
    strategies_fired = Column(Text)     # JSON array e.g. '["vcp","qullamaggie"]'
    theme_name = Column(Text)
    theme_momentum = Column(Text)
    theme_narrative = Column(Text)
    fit_strength = Column(Text)
    theme_score = Column(Float)
    pattern_notes = Column(Text)
    eps_yoy = Column(Float)
    eps_qoq = Column(Float)
    revenue_yoy = Column(Float)
    revenue_qoq = Column(Float)
    earnings_days_out = Column(Integer)


class StrategyParams(Base):
    __tablename__ = "strategy_params"

    id = Column(Integer, primary_key=True)
    user_id = Column(String(50), default="default", unique=True)
    base_max_depth_pct = Column(Float, default=0.35)
    base_min_weeks = Column(Integer, default=4)
    base_max_weeks = Column(Integer, default=52)
    prior_uptrend_min_pct = Column(Float, default=0.30)
    pivot_proximity_pct = Column(Float, default=0.05)
    rs_min_percentile = Column(Float, default=70.0)
    sma200_trend_weeks = Column(Integer, default=4)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AlertFeedback(Base):
    __tablename__ = "alert_feedback"

    id = Column(Integer, primary_key=True)
    alert_id = Column(Integer, ForeignKey("alerts.id"), nullable=False)
    action = Column(String(20))     # accept, reject, watch
    note = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class ForwardTest(Base):
    __tablename__ = "forward_tests"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), nullable=False)
    exchange = Column(String(10))
    currency = Column(String(5))
    strategy = Column(String(50))
    composite_score = Column(Float)

    entry_date = Column(Date, nullable=False)
    entry_price = Column(Float)
    entry_candle_low = Column(Float)   # low of entry day candle (initial stop reference)
    stop_price = Column(Float)         # active stop — can be manually adjusted
    pivot_price = Column(Float)

    check_date = Column(Date)          # entry_date + 60 days
    status = Column(String(20), default="pending")  # pending / completed / error

    # Evaluation results
    evaluated_at = Column(Date)
    sl_triggered = Column(Boolean)
    sl_trigger_date = Column(Date)
    max_high = Column(Float)
    min_low = Column(Float)
    max_mfe_pct = Column(Float)        # (max_high - entry_price) / entry_price
    max_mae_pct = Column(Float)        # (min_low - entry_price) / entry_price
    final_price = Column(Float)
    final_return_pct = Column(Float)

    __table_args__ = (UniqueConstraint("symbol", "entry_date", "strategy",
                                       name="uq_forward_test_symbol_date_strat"),)


def init_db():
    """Create all tables. Safe to call multiple times."""
    Base.metadata.create_all(bind=engine)


def drop_db():
    """Drop all tables. Destructive — only for development resets."""
    Base.metadata.drop_all(bind=engine)

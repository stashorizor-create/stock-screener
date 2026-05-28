-- Newsletter tables migration
-- Run in Supabase: SQL Editor → paste → Run

CREATE TABLE IF NOT EXISTS newsletter_market (
    id            SERIAL PRIMARY KEY,
    email_date    DATE NOT NULL UNIQUE,
    subject       TEXT,
    market_stance VARCHAR(20),
    market_notes  TEXT,
    raw_text      TEXT,
    processed_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS newsletter_picks (
    id                SERIAL PRIMARY KEY,
    email_date        DATE NOT NULL REFERENCES newsletter_market(email_date),
    ticker            VARCHAR(20) NOT NULL,
    action            VARCHAR(20),
    entry_price       FLOAT,
    stop_price        FLOAT,
    target_price      FLOAT,
    position_size_pct FLOAT,
    notes             TEXT,
    source_section    VARCHAR(50),
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_newsletter_pick
        UNIQUE (email_date, ticker, action, source_section)
);

CREATE INDEX IF NOT EXISTS idx_newsletter_picks_date   ON newsletter_picks(email_date);
CREATE INDEX IF NOT EXISTS idx_newsletter_picks_ticker ON newsletter_picks(ticker);

-- Add trim_2/trim_3 columns to newsletter_picks
-- Run in Supabase: SQL Editor → paste → Run

ALTER TABLE newsletter_picks
    ADD COLUMN IF NOT EXISTS trim_2 FLOAT,
    ADD COLUMN IF NOT EXISTS trim_3 FLOAT;

-- Forward test results table
CREATE TABLE IF NOT EXISTS newsletter_forward_tests (
    id                  SERIAL PRIMARY KEY,
    pick_id             INTEGER NOT NULL UNIQUE REFERENCES newsletter_picks(id),
    email_date          DATE NOT NULL,
    ticker              VARCHAR(20) NOT NULL,
    action              VARCHAR(20),
    entry_price         FLOAT,
    stop_price          FLOAT,
    trim_1              FLOAT,
    trim_2              FLOAT,
    trim_3              FLOAT,
    size_pct            FLOAT,

    evaluated_at        DATE,
    days_held           INTEGER,
    current_price       FLOAT,
    current_return_pct  FLOAT,
    max_high            FLOAT,
    max_mfe_pct         FLOAT,
    min_low             FLOAT,
    max_mae_pct         FLOAT,
    stop_hit            BOOLEAN DEFAULT FALSE,
    stop_hit_date       DATE,
    r_multiple          FLOAT,
    status              VARCHAR(20) DEFAULT 'active'
);

CREATE INDEX IF NOT EXISTS idx_nft_email_date ON newsletter_forward_tests(email_date);
CREATE INDEX IF NOT EXISTS idx_nft_ticker     ON newsletter_forward_tests(ticker);

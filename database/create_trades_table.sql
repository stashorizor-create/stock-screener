-- Run this once in Supabase SQL editor → SQL Editor → New query
-- Creates the trade journal table and disables RLS (personal tool, single user)

CREATE TABLE IF NOT EXISTS trades (
    id          SERIAL PRIMARY KEY,
    symbol      VARCHAR(20)  NOT NULL,
    strategy    VARCHAR(50),
    alert_date  DATE,
    entry_date  DATE         NOT NULL,
    entry_price FLOAT        NOT NULL,
    stop_price  FLOAT,
    target_price FLOAT,
    exit_date   DATE,
    exit_price  FLOAT,
    realized_rr FLOAT,                     -- (exit - entry) / (entry - stop)
    outcome     VARCHAR(20)  DEFAULT 'open', -- open / win / loss / breakeven
    notes       TEXT,
    created_at  TIMESTAMPTZ  DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_trades_outcome    ON trades(outcome);
CREATE INDEX IF NOT EXISTS idx_trades_entry_date ON trades(entry_date DESC);
CREATE INDEX IF NOT EXISTS idx_trades_symbol     ON trades(symbol);

-- Disable RLS — this is a private single-user tool
ALTER TABLE trades DISABLE ROW LEVEL SECURITY;

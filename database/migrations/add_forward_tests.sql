-- Migration: add forward_tests table for 60-day forward performance tracking
-- Run this in the Supabase SQL Editor (Dashboard → SQL Editor → New query)

CREATE TABLE IF NOT EXISTS forward_tests (
    id                SERIAL PRIMARY KEY,
    symbol            VARCHAR(20)   NOT NULL,
    exchange          VARCHAR(10),
    currency          VARCHAR(5),
    strategy          VARCHAR(50),
    composite_score   FLOAT,

    entry_date        DATE          NOT NULL,
    entry_price       FLOAT,
    entry_candle_low  FLOAT,        -- low of entry day candle (initial stop reference)
    stop_price        FLOAT,        -- active stop — update this to change the rule
    pivot_price       FLOAT,

    check_date        DATE,         -- entry_date + 60 days
    status            VARCHAR(20)   DEFAULT 'pending',  -- pending / completed / error

    -- Evaluation results (filled in after check_date)
    evaluated_at      DATE,
    sl_triggered      BOOLEAN,
    sl_trigger_date   DATE,
    max_high          FLOAT,
    min_low           FLOAT,
    max_mfe_pct       FLOAT,        -- (max_high - entry_price) / entry_price
    max_mae_pct       FLOAT,        -- (min_low  - entry_price) / entry_price
    final_price       FLOAT,
    final_return_pct  FLOAT,

    CONSTRAINT uq_forward_test_symbol_date_strat
        UNIQUE (symbol, entry_date, strategy)
);

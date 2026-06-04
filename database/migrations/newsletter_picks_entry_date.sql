-- Store Alex's actual entry date per position, read from the portfolio table's
-- date column. Previously the UI showed the newsletter date as a proxy "entry
-- date", which was misleading (a position is usually entered before the
-- newsletter that lists it). entry_date is also added to the unique key so the
-- same ticker scaled in on different dates stays as distinct positions.
--
-- Requires Postgres 15+ (Supabase). Run in Supabase: SQL Editor → Run.

ALTER TABLE newsletter_picks
    ADD COLUMN IF NOT EXISTS entry_date DATE;

ALTER TABLE newsletter_picks
    DROP CONSTRAINT IF EXISTS uq_newsletter_pick;

ALTER TABLE newsletter_picks
    ADD CONSTRAINT uq_newsletter_pick
        UNIQUE NULLS NOT DISTINCT
        (email_date, ticker, action, source_section, entry_price, entry_date);

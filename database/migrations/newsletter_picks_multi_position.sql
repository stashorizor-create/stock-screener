-- Allow several open positions in the SAME stock on one newsletter date.
-- Alex scales into a name across different dates/prices, so a ticker can appear
-- multiple times in the portfolio table (e.g. two INTC LONG rows with different
-- entries). The old unique key (email_date, ticker, action, source_section)
-- could only hold one of them and made batch upserts fail with
--   "ON CONFLICT DO UPDATE command cannot affect row a second time".
--
-- Fix: add entry_price to the key so distinct entries are distinct positions.
-- NULLS NOT DISTINCT keeps the old dedupe behaviour for rows that carry no
-- entry_price (focus_list / scan / ep / stalk), where NULL == NULL.
--
-- Requires Postgres 15+ (Supabase is fine). Run in Supabase: SQL Editor → Run.

ALTER TABLE newsletter_picks
    DROP CONSTRAINT IF EXISTS uq_newsletter_pick;

ALTER TABLE newsletter_picks
    ADD CONSTRAINT uq_newsletter_pick
        UNIQUE NULLS NOT DISTINCT
        (email_date, ticker, action, source_section, entry_price);

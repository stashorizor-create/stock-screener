-- Add trim_2 and trim_3 columns to newsletter_picks
-- These were in models.py but missing from the original migration.
-- Run in Supabase: SQL Editor → paste → Run
-- After running, re-ingest: python ingest_newsletter.py

ALTER TABLE newsletter_picks
  ADD COLUMN IF NOT EXISTS trim_2 FLOAT,
  ADD COLUMN IF NOT EXISTS trim_3 FLOAT;

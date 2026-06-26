-- Adds a JSON blob column to alerts holding per-strategy detail metrics
-- (e.g. the Ignition fingerprint: washout depth, thrust, volume surge, ADR
-- contraction, distance from the 200-day MA). Run in the Supabase SQL editor.
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS signal_detail TEXT;

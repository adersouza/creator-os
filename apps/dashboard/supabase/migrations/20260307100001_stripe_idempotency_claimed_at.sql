-- Add claimed_at to stripe_processed_events so stale processing locks can be
-- detected and re-claimed by Stripe retries after a Vercel function timeout.
-- A lock older than 5 minutes is considered stale (max Vercel duration is 60s).
ALTER TABLE stripe_processed_events
  ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

-- Stripe webhook event deduplication
-- Prevents double-processing when Stripe retries webhook delivery (up to 72h)
CREATE TABLE IF NOT EXISTS stripe_processed_events (
  event_id TEXT PRIMARY KEY,
  event_type TEXT NOT NULL,
  processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Auto-cleanup events older than 72 hours (Stripe retries for up to 72h)
CREATE INDEX IF NOT EXISTS idx_stripe_events_processed_at ON stripe_processed_events(processed_at);

-- RLS: Only service role can access
ALTER TABLE stripe_processed_events ENABLE ROW LEVEL SECURITY;
-- No RLS policies = only service role key can read/write (which is what API routes use)

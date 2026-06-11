-- Two-phase Stripe idempotency: tracks processing vs completed status
-- so failed events can be retried on Stripe's next delivery attempt.

-- Add status column (default 'completed' for existing rows)
ALTER TABLE stripe_processed_events
  ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'completed';

-- Index for the idempotency check: quickly find completed events
CREATE INDEX IF NOT EXISTS idx_stripe_events_status
  ON stripe_processed_events(event_id, status);

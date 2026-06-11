-- Instagram Webhook Events
-- Stores incoming webhook events from Meta for async processing
-- No RLS - server-side only access via service role

CREATE TABLE IF NOT EXISTS ig_webhook_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_type TEXT NOT NULL,
  ig_user_id TEXT NOT NULL,
  payload JSONB NOT NULL,
  received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  processed BOOLEAN NOT NULL DEFAULT false,
  processed_at TIMESTAMPTZ,
  error TEXT
);

-- Index for fetching unprocessed events efficiently
CREATE INDEX IF NOT EXISTS idx_ig_webhook_events_unprocessed
  ON ig_webhook_events(processed, received_at ASC)
  WHERE processed = false;

-- Index for querying events by type
CREATE INDEX IF NOT EXISTS idx_ig_webhook_events_type
  ON ig_webhook_events(event_type, received_at DESC);

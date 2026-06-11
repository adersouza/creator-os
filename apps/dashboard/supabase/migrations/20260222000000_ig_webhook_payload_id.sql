-- Add payload_id column to ig_webhook_events for deduplication
-- Mirrors the same pattern as threads_webhook_events (20260218120100)

ALTER TABLE ig_webhook_events
  ADD COLUMN IF NOT EXISTS payload_id text;

-- Backfill existing rows
UPDATE ig_webhook_events
  SET payload_id = payload->>'id'
  WHERE payload_id IS NULL AND payload->>'id' IS NOT NULL;

-- Also try mid (message ID) for messaging events
UPDATE ig_webhook_events
  SET payload_id = payload->>'mid'
  WHERE payload_id IS NULL AND payload->>'mid' IS NOT NULL;

-- Create unique constraint for deduplication
CREATE UNIQUE INDEX IF NOT EXISTS uq_ig_webhook_dedup
  ON ig_webhook_events (event_type, ig_user_id, payload_id)
  WHERE payload_id IS NOT NULL;

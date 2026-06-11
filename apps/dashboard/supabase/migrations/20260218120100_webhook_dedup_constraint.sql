-- Add payload_id column and unique constraint for webhook deduplication
-- Replaces SELECT-then-INSERT dedup with INSERT ON CONFLICT DO NOTHING

-- Add payload_id column extracted from payload JSON for efficient dedup
ALTER TABLE threads_webhook_events
  ADD COLUMN IF NOT EXISTS payload_id text;

-- Backfill existing rows
UPDATE threads_webhook_events
  SET payload_id = payload->>'id'
  WHERE payload_id IS NULL AND payload->>'id' IS NOT NULL;

-- Create unique constraint for deduplication
-- NULL payload_ids are allowed (events without payload.id are not deduped)
CREATE UNIQUE INDEX IF NOT EXISTS uq_threads_webhook_dedup
  ON threads_webhook_events (event_type, threads_user_id, payload_id)
  WHERE payload_id IS NOT NULL;

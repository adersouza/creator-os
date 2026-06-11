-- Add lifetime_retry_count to webhook event tables.
--
-- Unlike retry_count (which resets to 0 on each DLQ revival), this column
-- is monotonically increasing and gates the daily auto-retry sweep so a
-- single bad event cannot loop through the DLQ indefinitely.
--
-- PG 11+ handles ADD COLUMN NOT NULL DEFAULT as a metadata-only operation
-- (no table rewrite), so this is safe on large tables.

ALTER TABLE threads_webhook_events
  ADD COLUMN IF NOT EXISTS lifetime_retry_count INTEGER NOT NULL DEFAULT 0;

ALTER TABLE ig_webhook_events
  ADD COLUMN IF NOT EXISTS lifetime_retry_count INTEGER NOT NULL DEFAULT 0;

-- Migration: Threads Webhook Events table
-- Date: 2026-02-06
-- Purpose: Store incoming Threads webhook events for async processing
-- Note: This table may already exist if created manually. Using IF NOT EXISTS.

CREATE TABLE IF NOT EXISTS threads_webhook_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_type TEXT NOT NULL,         -- 'replies' | 'mentions' | 'publish'
  threads_user_id TEXT NOT NULL,    -- Threads user ID from webhook entry
  payload JSONB NOT NULL,
  received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  processed BOOLEAN NOT NULL DEFAULT false,
  processed_at TIMESTAMPTZ,
  error TEXT,
  retry_count INT DEFAULT 0
);

-- Index for fetching unprocessed events efficiently
CREATE INDEX IF NOT EXISTS idx_threads_webhook_pending
  ON threads_webhook_events(received_at ASC)
  WHERE processed = false;

-- Index for querying events by type
CREATE INDEX IF NOT EXISTS idx_threads_webhook_type
  ON threads_webhook_events(event_type, received_at DESC);

-- ============================================================================
-- Permissions
-- ============================================================================

ALTER TABLE threads_webhook_events DISABLE ROW LEVEL SECURITY;
GRANT ALL ON threads_webhook_events TO service_role;

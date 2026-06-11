-- Migration: Add retry columns to auto_post_queue and ig_webhook_events
-- Date: 2026-02-06
-- Purpose: Enable exponential backoff retry logic for failed jobs

-- ============================================================================
-- auto_post_queue — retry support
-- ============================================================================

ALTER TABLE auto_post_queue ADD COLUMN IF NOT EXISTS retry_count INT DEFAULT 0;
ALTER TABLE auto_post_queue ADD COLUMN IF NOT EXISTS next_retry_at TIMESTAMPTZ;
ALTER TABLE auto_post_queue ADD COLUMN IF NOT EXISTS last_error TEXT;

-- ============================================================================
-- ig_webhook_events — retry support (retry_count already exists from earlier migration)
-- ============================================================================

ALTER TABLE ig_webhook_events ADD COLUMN IF NOT EXISTS next_retry_at TIMESTAMPTZ;
ALTER TABLE ig_webhook_events ADD COLUMN IF NOT EXISTS last_error TEXT;

-- ============================================================================
-- threads_webhook_events — retry support
-- ============================================================================

CREATE TABLE IF NOT EXISTS threads_webhook_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_type TEXT NOT NULL,
  threads_user_id TEXT NOT NULL,
  payload JSONB NOT NULL,
  received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  processed BOOLEAN NOT NULL DEFAULT false,
  processed_at TIMESTAMPTZ,
  error TEXT,
  retry_count INT DEFAULT 0
);

ALTER TABLE threads_webhook_events ADD COLUMN IF NOT EXISTS next_retry_at TIMESTAMPTZ;
ALTER TABLE threads_webhook_events ADD COLUMN IF NOT EXISTS last_error TEXT;

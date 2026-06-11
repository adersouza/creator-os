-- Migration: Dead Letter Queue Pattern
-- Date: 2026-02-12
-- Purpose: Add DLQ status for items that exceed max retries,
--          enabling visibility and manual retry/purge of poisoned items.

-- ============================================================================
-- 1. Add dead_letter column to webhook event tables
-- ============================================================================

-- Threads webhook events: mark items that exceeded max retries
ALTER TABLE threads_webhook_events
  ADD COLUMN IF NOT EXISTS dead_letter BOOLEAN DEFAULT false;

ALTER TABLE threads_webhook_events
  ADD COLUMN IF NOT EXISTS dead_letter_at TIMESTAMPTZ;

ALTER TABLE threads_webhook_events
  ADD COLUMN IF NOT EXISTS dead_letter_reason TEXT;

-- Instagram webhook events: same pattern
ALTER TABLE ig_webhook_events
  ADD COLUMN IF NOT EXISTS dead_letter BOOLEAN DEFAULT false;

ALTER TABLE ig_webhook_events
  ADD COLUMN IF NOT EXISTS dead_letter_at TIMESTAMPTZ;

ALTER TABLE ig_webhook_events
  ADD COLUMN IF NOT EXISTS dead_letter_reason TEXT;

-- Auto-post queue: already has 'failed' status, add 'dead_letter' support
-- The status column is text, so we just use the value 'dead_letter'

-- IG pending containers: add DLQ support
ALTER TABLE ig_pending_containers
  ADD COLUMN IF NOT EXISTS dead_letter BOOLEAN DEFAULT false;

ALTER TABLE ig_pending_containers
  ADD COLUMN IF NOT EXISTS dead_letter_at TIMESTAMPTZ;

ALTER TABLE ig_pending_containers
  ADD COLUMN IF NOT EXISTS dead_letter_reason TEXT;

-- ============================================================================
-- 2. Indexes for DLQ queries
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_threads_webhook_dlq
  ON threads_webhook_events(dead_letter_at DESC)
  WHERE dead_letter = true;

CREATE INDEX IF NOT EXISTS idx_ig_webhook_dlq
  ON ig_webhook_events(dead_letter_at DESC)
  WHERE dead_letter = true;

CREATE INDEX IF NOT EXISTS idx_auto_post_queue_dlq
  ON auto_post_queue(created_at DESC)
  WHERE status = 'dead_letter';

CREATE INDEX IF NOT EXISTS idx_ig_containers_dlq
  ON ig_pending_containers(dead_letter_at DESC)
  WHERE dead_letter = true;

-- ============================================================================
-- 3. View for admin dashboard — all dead letter items across tables
-- ============================================================================

CREATE OR REPLACE VIEW dead_letter_items AS
  SELECT
    'threads_webhook' AS source,
    id::text AS item_id,
    event_type AS item_type,
    dead_letter_reason AS reason,
    dead_letter_at,
    retry_count,
    error AS last_error
  FROM threads_webhook_events
  WHERE dead_letter = true

  UNION ALL

  SELECT
    'ig_webhook' AS source,
    id::text AS item_id,
    event_type AS item_type,
    dead_letter_reason AS reason,
    dead_letter_at,
    retry_count,
    error AS last_error
  FROM ig_webhook_events
  WHERE dead_letter = true

  UNION ALL

  SELECT
    'auto_post_queue' AS source,
    id::text AS item_id,
    'auto_post' AS item_type,
    error_message AS reason,
    created_at AS dead_letter_at,
    retry_count,
    error_message AS last_error
  FROM auto_post_queue
  WHERE status = 'dead_letter'

  UNION ALL

  SELECT
    'ig_container' AS source,
    id::text AS item_id,
    'container_publish' AS item_type,
    dead_letter_reason AS reason,
    dead_letter_at,
    check_count AS retry_count,
    error AS last_error
  FROM ig_pending_containers
  WHERE dead_letter = true
ORDER BY dead_letter_at DESC;

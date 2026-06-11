-- Migration: Medium Severity Database Fixes
-- Date: 2026-02-13
-- Purpose: Fix overly permissive RLS policy on group_analytics,
--          add missing CHECK constraints on status fields.

-- ============================================================================
-- 1. D3 — Fix overly permissive RLS policy on group_analytics
-- ============================================================================
-- The existing policy "Service role full access to group analytics" uses
-- USING (true) WITH CHECK (true) without specifying TO service_role,
-- which grants full access to ALL roles (including anon/authenticated).
-- Drop and recreate with explicit TO service_role targeting.

DROP POLICY IF EXISTS "Service role full access to group analytics" ON group_analytics;

CREATE POLICY "Service role full access to group analytics"
  ON group_analytics FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

-- ============================================================================
-- 2. D5 — Missing CHECK constraints on status fields
-- ============================================================================

-- 2a. auto_post_queue.status
-- Valid values: pending, queued, processing, published, failed, cancelled, dead_letter
-- NOT VALID = only enforce on new/updated rows, skip existing data
DO $$ BEGIN
  ALTER TABLE auto_post_queue ADD CONSTRAINT chk_auto_post_queue_status
    CHECK (status IN ('pending', 'queued', 'processing', 'published', 'failed', 'cancelled', 'dead_letter'))
    NOT VALID;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- 2b. sync_jobs.status
-- Already has CHECK constraint from original table creation (20250125_sync_jobs_table.sql):
--   CHECK (status IN ('queued', 'processing', 'completed', 'failed'))
-- No action needed.

-- 2c. ig_pending_containers.status
-- Valid values: pending, ready, published, failed, dead_letter
DO $$ BEGIN
  ALTER TABLE ig_pending_containers ADD CONSTRAINT chk_ig_pending_containers_status
    CHECK (status IN ('pending', 'ready', 'published', 'failed', 'dead_letter'))
    NOT VALID;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

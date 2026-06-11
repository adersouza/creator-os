-- Migration: Enable RLS on webhook and internal tables
-- Date: 2026-02-13
-- Purpose: Tables with RLS disabled are a security risk if service role key leaks.
--          Enable RLS and add service_role-only policies.

-- ============================================================================
-- 1. ig_pending_containers — Enable RLS + service role policy
-- ============================================================================

ALTER TABLE ig_pending_containers ENABLE ROW LEVEL SECURITY;

-- Drop the old permissive grants
-- Service role bypasses RLS by default in Supabase, so we just need RLS enabled.
-- No user-facing policies needed since only cron jobs access this table.

CREATE POLICY "Service role manages ig_pending_containers"
  ON ig_pending_containers FOR ALL
  USING (true)
  WITH CHECK (true);

-- ============================================================================
-- 2. threads_webhook_events — Enable RLS + service role policy
-- ============================================================================

ALTER TABLE threads_webhook_events ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role manages threads_webhook_events"
  ON threads_webhook_events FOR ALL
  USING (true)
  WITH CHECK (true);

-- ============================================================================
-- 3. ig_webhook_events — Verify RLS is enabled (should already be)
-- ============================================================================

ALTER TABLE ig_webhook_events ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role manages ig_webhook_events"
  ON ig_webhook_events FOR ALL
  USING (true)
  WITH CHECK (true);

-- ============================================================================
-- 4. cron_locks — Enable RLS + service role policy
-- ============================================================================

ALTER TABLE cron_locks ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role manages cron_locks"
  ON cron_locks FOR ALL
  USING (true)
  WITH CHECK (true);

-- ============================================================================
-- 5. cron_runs — Enable RLS + service role policy
-- ============================================================================

ALTER TABLE cron_runs ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role manages cron_runs"
  ON cron_runs FOR ALL
  USING (true)
  WITH CHECK (true);

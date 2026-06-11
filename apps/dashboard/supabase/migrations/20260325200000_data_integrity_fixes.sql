-- ============================================================================
-- Migration: Data Integrity Fixes
-- ============================================================================
-- Date: 2026-03-25
--
-- Addresses multiple constraint, column, and RPC issues discovered during
-- production data integrity audit:
--
--   1a. auto_post_queue.status CHECK — add back 'publishing' (used by publish pipeline)
--   1b. auto_post_queue.source_type CHECK — drop entirely (too brittle, new types added often)
--   1c. ig_pending_containers.status CHECK — add 'failed' and 'dead_letter'
--   1d. auto_post_queue.engagement_rate — widen from DECIMAL(5,4) to DECIMAL(10,4)
--   1e. auto_post_group_state — add IG state columns for Instagram autoposter
--   1f. auto_post_queue — add claimed_at column for atomic claim tracking
--   1g. account_groups — ensure content_strategy JSONB column exists
--   1h. get_rate_limit_status RPC — accept limit parameters with defaults
-- ============================================================================

BEGIN;

-- ============================================================================
-- 1a. Fix auto_post_queue.status CHECK — add back 'publishing'
-- ============================================================================
-- The publish pipeline transitions items to 'publishing' before calling the
-- Meta API. Previous migration accidentally omitted this status.

ALTER TABLE auto_post_queue DROP CONSTRAINT IF EXISTS auto_post_queue_status_check;
ALTER TABLE auto_post_queue ADD CONSTRAINT auto_post_queue_status_check
  CHECK (status IN ('pending','processing','publishing','posted','published','failed',
                    'dead_letter','cancelled','rejected','queued','scheduled'));

-- ============================================================================
-- 1b. Drop auto_post_queue.source_type CHECK entirely
-- ============================================================================
-- New source types are added regularly (competitor_copy, evergreen, manual, etc.)
-- A CHECK constraint here is too brittle and causes silent insert failures.

ALTER TABLE auto_post_queue DROP CONSTRAINT IF EXISTS auto_post_queue_source_type_check;

-- ============================================================================
-- 1c. Fix ig_pending_containers.status CHECK
-- ============================================================================
-- The IG container publisher can transition containers to 'failed' and
-- 'dead_letter' but the CHECK constraint did not include these statuses.

ALTER TABLE ig_pending_containers DROP CONSTRAINT IF EXISTS chk_ig_pending_containers_status;
ALTER TABLE ig_pending_containers ADD CONSTRAINT chk_ig_pending_containers_status
  CHECK (status IN ('pending','processing','ready','error','published','failed','dead_letter'));

-- ============================================================================
-- 1d. Widen auto_post_queue.engagement_rate from DECIMAL(5,4) to DECIMAL(10,4)
-- ============================================================================
-- DECIMAL(5,4) maxes out at 9.9999 — viral posts can have engagement rates
-- exceeding 10.0 (e.g., 1000% = 10.0). Widen to DECIMAL(10,4) for headroom.

ALTER TABLE auto_post_queue ALTER COLUMN engagement_rate TYPE DECIMAL(10,4);

-- ============================================================================
-- 1e. Add IG state columns to auto_post_group_state
-- ============================================================================
-- The Instagram autoposter needs its own counters separate from Threads.
-- Without these columns, IG posts_today/last_post_at share Threads state,
-- causing incorrect rate limiting across platforms.

ALTER TABLE auto_post_group_state
  ADD COLUMN IF NOT EXISTS ig_posts_today INTEGER DEFAULT 0,
  ADD COLUMN IF NOT EXISTS ig_last_post_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS ig_current_account_index INTEGER DEFAULT 0,
  ADD COLUMN IF NOT EXISTS ig_current_queue_index INTEGER DEFAULT 0;

-- ============================================================================
-- 1f. Add claimed_at column to auto_post_queue
-- ============================================================================
-- Used for atomic claim tracking — the publish worker sets claimed_at when it
-- picks up an item, enabling stale-claim detection and requeue logic.

ALTER TABLE auto_post_queue ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMPTZ;

-- ============================================================================
-- 1g. Ensure content_strategy JSONB on account_groups
-- ============================================================================
-- Per-persona content strategy (topics, tone, competitor_ids, posting cadence).
-- May already exist from a previous migration — IF NOT EXISTS is safe.

ALTER TABLE account_groups ADD COLUMN IF NOT EXISTS content_strategy JSONB;

-- ============================================================================
-- 1h. Fix get_rate_limit_status RPC — accept limit parameters with defaults
-- ============================================================================
-- Problems with the existing function:
--   - Hardcoded hourly_limit=3 and daily_limit=20, but callers use 25/250
--   - Parameter type was UUID but rate_limit_tracking.account_id is TEXT
--   - Column references (hour_window_start, posts_this_hour) did not match
--     current schema (hourly_reset_at, hourly_count)
--
-- This replaces both the UUID overload and the TEXT/JSONB overload with a
-- single TEXT overload that returns TABLE and accepts configurable limits.

-- Drop the old UUID overload so we don't have ambiguous function resolution
DROP FUNCTION IF EXISTS get_rate_limit_status(UUID);

CREATE OR REPLACE FUNCTION get_rate_limit_status(
  p_account_id TEXT,
  p_hourly_limit INTEGER DEFAULT 25,
  p_daily_limit INTEGER DEFAULT 250
)
RETURNS TABLE (
  posts_this_hour INTEGER,
  posts_today INTEGER,
  hourly_remaining INTEGER,
  daily_remaining INTEGER,
  next_hour_reset TIMESTAMPTZ,
  next_day_reset TIMESTAMPTZ
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_record rate_limit_tracking%ROWTYPE;
  v_now TIMESTAMPTZ := NOW();
  v_today DATE := CURRENT_DATE;
  v_hour_ago TIMESTAMPTZ := v_now - INTERVAL '1 hour';
  v_hourly INTEGER;
  v_daily INTEGER;
BEGIN
  SELECT * INTO v_record FROM rate_limit_tracking WHERE account_id = p_account_id;

  IF v_record IS NULL THEN
    RETURN QUERY SELECT
      0,
      0,
      p_hourly_limit,
      p_daily_limit,
      v_now + INTERVAL '1 hour',
      (v_today + 1)::TIMESTAMPTZ;
    RETURN;
  END IF;

  -- Reset counters if their window has expired
  v_hourly := v_record.hourly_count;
  v_daily := v_record.daily_count;

  IF v_record.hourly_reset_at < v_hour_ago THEN
    v_hourly := 0;
  END IF;
  IF v_record.daily_reset_at::DATE < v_today THEN
    v_daily := 0;
  END IF;

  RETURN QUERY SELECT
    v_hourly,
    v_daily,
    GREATEST(0, p_hourly_limit - v_hourly),
    GREATEST(0, p_daily_limit - v_daily),
    COALESCE(v_record.hourly_reset_at, v_now) + INTERVAL '1 hour',
    (COALESCE(v_record.daily_reset_at, v_now)::DATE + 1)::TIMESTAMPTZ;
END;
$$;

-- Grant execute to service_role (callers use Supabase service key)
REVOKE EXECUTE ON FUNCTION get_rate_limit_status(TEXT, INTEGER, INTEGER) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION get_rate_limit_status(TEXT, INTEGER, INTEGER) FROM anon;
REVOKE EXECUTE ON FUNCTION get_rate_limit_status(TEXT, INTEGER, INTEGER) FROM authenticated;
GRANT EXECUTE ON FUNCTION get_rate_limit_status(TEXT, INTEGER, INTEGER) TO service_role;

COMMIT;

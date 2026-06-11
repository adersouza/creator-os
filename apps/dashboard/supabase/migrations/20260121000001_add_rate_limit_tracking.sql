-- Migration: Add Rate Limit Tracking Table
-- Date: 2026-01-21
-- Purpose: Fix race condition in scheduled posts by tracking rate limits in database
--
-- Problem: The current in-memory rate limit tracking resets between cron executions,
-- allowing concurrent cron runs to bypass the 3 posts/hour and 20 posts/day limits.
--
-- Solution: Track rate limits per-account in the database with row-level locking.

-- ============================================================================
-- Rate Limit Tracking Table
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.rate_limit_tracking (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id TEXT NOT NULL REFERENCES public.accounts(id) ON DELETE CASCADE,

  -- Hourly tracking
  posts_this_hour INTEGER DEFAULT 0,
  hour_window_start TIMESTAMPTZ DEFAULT NOW(),

  -- Daily tracking
  posts_today INTEGER DEFAULT 0,
  date DATE DEFAULT CURRENT_DATE,
  day_window_start TIMESTAMPTZ DEFAULT (CURRENT_DATE)::TIMESTAMPTZ,

  -- Metadata
  last_post_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),

  -- One record per account
  UNIQUE(account_id)
);

-- Index for fast lookups by account
CREATE INDEX IF NOT EXISTS idx_rate_limit_tracking_account_id
ON public.rate_limit_tracking(account_id);

-- ============================================================================
-- Function: Increment Rate Limit Counter
-- ============================================================================
-- This function atomically increments the post counter and checks limits.
-- Returns: { allowed: boolean, reason?: string }
--
-- Usage:
--   SELECT * FROM check_and_increment_rate_limit('account-uuid', 3, 20);

CREATE OR REPLACE FUNCTION check_and_increment_rate_limit(
  p_account_id TEXT,
  p_hourly_limit INTEGER DEFAULT 3,
  p_daily_limit INTEGER DEFAULT 20
)
RETURNS TABLE (
  allowed BOOLEAN,
  reason TEXT,
  posts_this_hour INTEGER,
  posts_today INTEGER
)
LANGUAGE plpgsql
AS $$
DECLARE
  v_record rate_limit_tracking%ROWTYPE;
  v_now TIMESTAMPTZ := NOW();
  v_today DATE := CURRENT_DATE;
  v_hour_ago TIMESTAMPTZ := v_now - INTERVAL '1 hour';
BEGIN
  -- Get or create record with row-level lock
  INSERT INTO rate_limit_tracking (account_id, posts_this_hour, posts_today, hour_window_start, day_window_start)
  VALUES (p_account_id, 0, 0, v_now, v_today::TIMESTAMPTZ)
  ON CONFLICT (account_id) DO UPDATE
  SET updated_at = v_now
  RETURNING * INTO v_record;

  -- Lock the row for update
  SELECT * INTO v_record
  FROM rate_limit_tracking
  WHERE account_id = p_account_id
  FOR UPDATE;

  -- Reset hourly counter if window expired
  IF v_record.hour_window_start < v_hour_ago THEN
    v_record.posts_this_hour := 0;
    v_record.hour_window_start := v_now;
  END IF;

  -- Reset daily counter if new day
  IF v_record.day_window_start::DATE < v_today THEN
    v_record.posts_today := 0;
    v_record.day_window_start := v_today::TIMESTAMPTZ;
  END IF;

  -- Check limits
  IF v_record.posts_this_hour >= p_hourly_limit THEN
    RETURN QUERY SELECT
      FALSE,
      FORMAT('Hourly limit reached (%s/%s)', v_record.posts_this_hour, p_hourly_limit),
      v_record.posts_this_hour,
      v_record.posts_today;
    RETURN;
  END IF;

  IF v_record.posts_today >= p_daily_limit THEN
    RETURN QUERY SELECT
      FALSE,
      FORMAT('Daily limit reached (%s/%s)', v_record.posts_today, p_daily_limit),
      v_record.posts_this_hour,
      v_record.posts_today;
    RETURN;
  END IF;

  -- Increment counters
  UPDATE rate_limit_tracking
  SET
    posts_this_hour = v_record.posts_this_hour + 1,
    posts_today = v_record.posts_today + 1,
    hour_window_start = v_record.hour_window_start,
    day_window_start = v_record.day_window_start,
    last_post_at = v_now,
    updated_at = v_now
  WHERE account_id = p_account_id;

  -- Return success
  RETURN QUERY SELECT
    TRUE,
    NULL::TEXT,
    v_record.posts_this_hour + 1,
    v_record.posts_today + 1;
END;
$$;

-- ============================================================================
-- Function: Get Rate Limit Status (Read-only)
-- ============================================================================
-- Returns current rate limit status without incrementing.
--
-- Usage:
--   SELECT * FROM get_rate_limit_status('account-uuid');

CREATE OR REPLACE FUNCTION get_rate_limit_status(p_account_id TEXT)
RETURNS TABLE (
  posts_this_hour INTEGER,
  posts_today INTEGER,
  hourly_remaining INTEGER,
  daily_remaining INTEGER,
  next_hour_reset TIMESTAMPTZ,
  next_day_reset TIMESTAMPTZ
)
LANGUAGE plpgsql
AS $$
DECLARE
  v_record rate_limit_tracking%ROWTYPE;
  v_now TIMESTAMPTZ := NOW();
  v_today DATE := CURRENT_DATE;
  v_hour_ago TIMESTAMPTZ := v_now - INTERVAL '1 hour';
  v_hourly_limit INTEGER := 3;
  v_daily_limit INTEGER := 20;
BEGIN
  -- Get record
  SELECT * INTO v_record
  FROM rate_limit_tracking
  WHERE account_id = p_account_id;

  -- If no record, return zeros
  IF v_record IS NULL THEN
    RETURN QUERY SELECT
      0, 0,
      v_hourly_limit, v_daily_limit,
      v_now + INTERVAL '1 hour',
      (v_today + 1)::TIMESTAMPTZ;
    RETURN;
  END IF;

  -- Adjust for window resets
  IF v_record.hour_window_start < v_hour_ago THEN
    v_record.posts_this_hour := 0;
  END IF;

  IF v_record.day_window_start::DATE < v_today THEN
    v_record.posts_today := 0;
  END IF;

  RETURN QUERY SELECT
    v_record.posts_this_hour,
    v_record.posts_today,
    GREATEST(0, v_hourly_limit - v_record.posts_this_hour),
    GREATEST(0, v_daily_limit - v_record.posts_today),
    v_record.hour_window_start + INTERVAL '1 hour',
    (v_record.day_window_start::DATE + 1)::TIMESTAMPTZ;
END;
$$;

-- ============================================================================
-- Grant permissions
-- ============================================================================
-- Allow the service role to use these functions

DO $$
BEGIN
  IF to_regprocedure('public.check_and_increment_rate_limit(text, integer, integer)') IS NOT NULL THEN
    GRANT EXECUTE ON FUNCTION check_and_increment_rate_limit(TEXT, INTEGER, INTEGER) TO service_role;
  END IF;

  IF to_regprocedure('public.get_rate_limit_status(text)') IS NOT NULL THEN
    GRANT EXECUTE ON FUNCTION get_rate_limit_status(TEXT) TO service_role;
  END IF;
END;
$$;
GRANT ALL ON TABLE rate_limit_tracking TO service_role;

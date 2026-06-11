-- Migration: Unified Publish Rate Limit Check
-- Date: 2026-02-08
-- Purpose: Add check_publish_rate_limit() function for use in the publish API endpoint
-- Approach: Counter-table approach using existing rate_limit_tracking / ig_rate_limit_tracking tables
-- (NOT posts-table-scanning — see Correction 4 in execution prompt)

-- ============================================================================
-- Function: check_publish_rate_limit
-- ============================================================================
-- Unified rate limit check for both Threads and Instagram publishing.
-- Delegates to existing platform-specific counter-table functions.
--
-- Threads: 25/hour, 200/day safety buffer (API limit is 250/day)
-- Instagram: 25/day safety buffer (API limit is 50/day)
--
-- Usage:
--   SELECT * FROM check_publish_rate_limit('account-uuid'::UUID, 'threads');
--   SELECT * FROM check_publish_rate_limit('ig-account-uuid'::UUID, 'instagram');

CREATE OR REPLACE FUNCTION check_publish_rate_limit(
  p_account_id UUID,
  p_platform TEXT DEFAULT 'threads'
) RETURNS TABLE(allowed BOOLEAN, reason TEXT, daily_used INT, daily_limit INT)
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  v_allowed BOOLEAN;
  v_reason TEXT;
  v_daily INT;
  v_hourly INT;
BEGIN
  IF p_platform = 'instagram' THEN
    -- Instagram: 25/day safety buffer (API limit is 50/day)
    SELECT r.allowed, r.reason
    INTO v_allowed, v_reason
    FROM ig_check_and_increment_rate_limit(p_account_id, 25) r;

    -- Get current count for response
    SELECT COALESCE(daily_count, 0)
    INTO v_daily
    FROM ig_rate_limit_tracking
    WHERE account_id = p_account_id;

    RETURN QUERY SELECT v_allowed, v_reason, COALESCE(v_daily, 0)::INT, 25;
  ELSE
    -- Threads: 25/hour, 200/day safety buffer (API limit is 250/day)
    SELECT r.allowed, r.reason, r.posts_today
    INTO v_allowed, v_reason, v_daily
    FROM check_and_increment_rate_limit(p_account_id, 25, 200) r;

    RETURN QUERY SELECT v_allowed, v_reason, COALESCE(v_daily, 0)::INT, 200;
  END IF;
END;
$$;

-- ============================================================================
-- Grant permissions
-- ============================================================================
GRANT EXECUTE ON FUNCTION check_publish_rate_limit TO service_role;

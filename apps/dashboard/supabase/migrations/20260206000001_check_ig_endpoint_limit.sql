-- Migration: IG Endpoint Rate Limit Function
-- Date: 2026-02-06
-- Purpose: Per-endpoint rate limiting for Instagram API routes
-- Extends the pattern from check_and_increment_rate_limit but scoped by endpoint

-- ============================================================================
-- Rate limit tracking table for IG endpoints
-- ============================================================================

CREATE TABLE IF NOT EXISTS ig_endpoint_rate_limits (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id UUID NOT NULL,
  endpoint TEXT NOT NULL,  -- 'comments' | 'messages' | 'hashtags'

  -- Hourly tracking
  requests_this_hour INT DEFAULT 0,
  hour_window_start TIMESTAMPTZ DEFAULT NOW(),

  -- Daily tracking
  requests_today INT DEFAULT 0,
  day_window_start TIMESTAMPTZ DEFAULT (CURRENT_DATE)::TIMESTAMPTZ,

  last_request_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),

  UNIQUE(account_id, endpoint)
);

CREATE INDEX IF NOT EXISTS idx_ig_endpoint_limits_lookup
  ON ig_endpoint_rate_limits(account_id, endpoint);

-- ============================================================================
-- Function: Check and increment IG endpoint rate limit
-- ============================================================================

CREATE OR REPLACE FUNCTION check_ig_endpoint_limit(
  p_account_id UUID,
  p_endpoint TEXT,
  p_hourly_limit INT,
  p_daily_limit INT
) RETURNS TABLE(allowed BOOLEAN, reason TEXT) AS $$
DECLARE
  v_record ig_endpoint_rate_limits%ROWTYPE;
  v_now TIMESTAMPTZ := NOW();
  v_today DATE := CURRENT_DATE;
  v_hour_ago TIMESTAMPTZ := v_now - INTERVAL '1 hour';
BEGIN
  -- Get or create record with row-level lock
  INSERT INTO ig_endpoint_rate_limits (account_id, endpoint, requests_this_hour, requests_today, hour_window_start, day_window_start)
  VALUES (p_account_id, p_endpoint, 0, 0, v_now, v_today::TIMESTAMPTZ)
  ON CONFLICT (account_id, endpoint) DO UPDATE
  SET last_request_at = v_now
  RETURNING * INTO v_record;

  -- Lock the row for update
  SELECT * INTO v_record
  FROM ig_endpoint_rate_limits
  WHERE account_id = p_account_id AND endpoint = p_endpoint
  FOR UPDATE;

  -- Reset hourly counter if window expired
  IF v_record.hour_window_start < v_hour_ago THEN
    v_record.requests_this_hour := 0;
    v_record.hour_window_start := v_now;
  END IF;

  -- Reset daily counter if new day
  IF v_record.day_window_start::DATE < v_today THEN
    v_record.requests_today := 0;
    v_record.day_window_start := v_today::TIMESTAMPTZ;
  END IF;

  -- Check hourly limit
  IF p_hourly_limit > 0 AND v_record.requests_this_hour >= p_hourly_limit THEN
    RETURN QUERY SELECT
      FALSE,
      FORMAT('Hourly limit reached (%s/%s) for %s', v_record.requests_this_hour, p_hourly_limit, p_endpoint);
    RETURN;
  END IF;

  -- Check daily limit
  IF p_daily_limit > 0 AND v_record.requests_today >= p_daily_limit THEN
    RETURN QUERY SELECT
      FALSE,
      FORMAT('Daily limit reached (%s/%s) for %s', v_record.requests_today, p_daily_limit, p_endpoint);
    RETURN;
  END IF;

  -- Increment counters
  UPDATE ig_endpoint_rate_limits
  SET
    requests_this_hour = v_record.requests_this_hour + 1,
    requests_today = v_record.requests_today + 1,
    hour_window_start = v_record.hour_window_start,
    day_window_start = v_record.day_window_start,
    last_request_at = v_now
  WHERE account_id = p_account_id AND endpoint = p_endpoint;

  -- Return success
  RETURN QUERY SELECT TRUE, NULL::TEXT;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- Permissions
-- ============================================================================

GRANT ALL ON ig_endpoint_rate_limits TO service_role;
GRANT EXECUTE ON FUNCTION check_ig_endpoint_limit TO service_role;

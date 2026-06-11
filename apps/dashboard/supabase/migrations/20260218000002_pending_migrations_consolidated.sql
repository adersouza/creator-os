-- Consolidated pending migrations: rate limiting + cron cleanup
-- Combines: 20260121000001, 20260130000004 (rate limit parts), 20260130000005, 20260208000001
-- Plus: cron_runs auto-cleanup, search_path fixes

-- ============================================================================
-- 1. Rate Limit Tracking Table (from 20260121000001)
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.rate_limit_tracking (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id UUID NOT NULL,
  posts_this_hour INTEGER DEFAULT 0,
  hour_window_start TIMESTAMPTZ DEFAULT NOW(),
  posts_today INTEGER DEFAULT 0,
  day_window_start TIMESTAMPTZ DEFAULT (CURRENT_DATE)::TIMESTAMPTZ,
  last_post_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(account_id)
);

CREATE INDEX IF NOT EXISTS idx_rate_limit_tracking_account_id
  ON public.rate_limit_tracking(account_id);

-- ============================================================================
-- 2. IG Rate Limit Tracking Table
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.ig_rate_limit_tracking (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id UUID NOT NULL UNIQUE,
  daily_count INTEGER DEFAULT 0,
  daily_reset_at TIMESTAMPTZ DEFAULT NOW() + INTERVAL '24 hours',
  last_reset_at TIMESTAMPTZ DEFAULT NOW(),
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================================
-- 3. Threads rate limit function (from 20260121000001)
-- ============================================================================

CREATE OR REPLACE FUNCTION check_and_increment_rate_limit(
  p_account_id UUID,
  p_hourly_limit INTEGER DEFAULT 3,
  p_daily_limit INTEGER DEFAULT 20
)
RETURNS TABLE (allowed BOOLEAN, reason TEXT, posts_this_hour INTEGER, posts_today INTEGER)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
  v_record rate_limit_tracking%ROWTYPE;
  v_now TIMESTAMPTZ := NOW();
  v_today DATE := CURRENT_DATE;
  v_hour_ago TIMESTAMPTZ := v_now - INTERVAL '1 hour';
BEGIN
  INSERT INTO rate_limit_tracking (account_id, posts_this_hour, posts_today, hour_window_start, day_window_start)
  VALUES (p_account_id, 0, 0, v_now, v_today::TIMESTAMPTZ)
  ON CONFLICT (account_id) DO UPDATE SET updated_at = v_now
  RETURNING * INTO v_record;

  SELECT * INTO v_record FROM rate_limit_tracking WHERE account_id = p_account_id FOR UPDATE;

  IF v_record.hour_window_start < v_hour_ago THEN
    v_record.posts_this_hour := 0;
    v_record.hour_window_start := v_now;
  END IF;

  IF v_record.day_window_start::DATE < v_today THEN
    v_record.posts_today := 0;
    v_record.day_window_start := v_today::TIMESTAMPTZ;
  END IF;

  IF v_record.posts_this_hour >= p_hourly_limit THEN
    RETURN QUERY SELECT FALSE, FORMAT('Hourly limit reached (%s/%s)', v_record.posts_this_hour, p_hourly_limit), v_record.posts_this_hour, v_record.posts_today;
    RETURN;
  END IF;

  IF v_record.posts_today >= p_daily_limit THEN
    RETURN QUERY SELECT FALSE, FORMAT('Daily limit reached (%s/%s)', v_record.posts_today, p_daily_limit), v_record.posts_this_hour, v_record.posts_today;
    RETURN;
  END IF;

  UPDATE rate_limit_tracking SET
    posts_this_hour = v_record.posts_this_hour + 1,
    posts_today = v_record.posts_today + 1,
    hour_window_start = v_record.hour_window_start,
    day_window_start = v_record.day_window_start,
    last_post_at = v_now,
    updated_at = v_now
  WHERE account_id = p_account_id;

  RETURN QUERY SELECT TRUE, NULL::TEXT, v_record.posts_this_hour + 1, v_record.posts_today + 1;
END;
$$;

-- ============================================================================
-- 4. Read-only rate limit status (from 20260121000001)
-- ============================================================================

CREATE OR REPLACE FUNCTION get_rate_limit_status(p_account_id UUID)
RETURNS TABLE (posts_this_hour INTEGER, posts_today INTEGER, hourly_remaining INTEGER, daily_remaining INTEGER, next_hour_reset TIMESTAMPTZ, next_day_reset TIMESTAMPTZ)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
  v_record rate_limit_tracking%ROWTYPE;
  v_now TIMESTAMPTZ := NOW();
  v_today DATE := CURRENT_DATE;
  v_hour_ago TIMESTAMPTZ := v_now - INTERVAL '1 hour';
  v_hourly_limit INTEGER := 3;
  v_daily_limit INTEGER := 20;
BEGIN
  SELECT * INTO v_record FROM rate_limit_tracking WHERE account_id = p_account_id;

  IF v_record IS NULL THEN
    RETURN QUERY SELECT 0, 0, v_hourly_limit, v_daily_limit, v_now + INTERVAL '1 hour', (v_today + 1)::TIMESTAMPTZ;
    RETURN;
  END IF;

  IF v_record.hour_window_start < v_hour_ago THEN v_record.posts_this_hour := 0; END IF;
  IF v_record.day_window_start::DATE < v_today THEN v_record.posts_today := 0; END IF;

  RETURN QUERY SELECT
    v_record.posts_this_hour, v_record.posts_today,
    GREATEST(0, v_hourly_limit - v_record.posts_this_hour),
    GREATEST(0, v_daily_limit - v_record.posts_today),
    v_record.hour_window_start + INTERVAL '1 hour',
    (v_record.day_window_start::DATE + 1)::TIMESTAMPTZ;
END;
$$;

-- ============================================================================
-- 5. IG rate limit function (from 20260130000005 — updated to 50/day)
-- ============================================================================

CREATE OR REPLACE FUNCTION ig_check_and_increment_rate_limit(
  p_account_id UUID,
  p_daily_limit INTEGER DEFAULT 50
)
RETURNS TABLE(allowed BOOLEAN, reason TEXT)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
  v_daily_count INTEGER;
BEGIN
  PERFORM 1 FROM ig_rate_limit_tracking WHERE account_id = p_account_id FOR UPDATE;

  INSERT INTO ig_rate_limit_tracking (account_id, daily_count, last_reset_at)
  VALUES (p_account_id, 0, NOW())
  ON CONFLICT (account_id) DO NOTHING;

  UPDATE ig_rate_limit_tracking SET daily_count = 0, last_reset_at = NOW()
  WHERE account_id = p_account_id AND last_reset_at < NOW() - INTERVAL '24 hours';

  SELECT t.daily_count INTO v_daily_count FROM ig_rate_limit_tracking t WHERE t.account_id = p_account_id;

  IF v_daily_count >= p_daily_limit THEN
    RETURN QUERY SELECT FALSE, FORMAT('Daily limit reached (%s/%s)', v_daily_count, p_daily_limit);
    RETURN;
  END IF;

  UPDATE ig_rate_limit_tracking SET daily_count = daily_count + 1 WHERE account_id = p_account_id;
  RETURN QUERY SELECT TRUE, NULL::TEXT;
END;
$$;

-- ============================================================================
-- 6. Unified publish rate limit (from 20260208000001)
-- ============================================================================

CREATE OR REPLACE FUNCTION check_publish_rate_limit(
  p_account_id UUID,
  p_platform TEXT DEFAULT 'threads'
) RETURNS TABLE(allowed BOOLEAN, reason TEXT, daily_used INT, daily_limit INT)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
  v_allowed BOOLEAN;
  v_reason TEXT;
  v_daily INT;
BEGIN
  IF p_platform = 'instagram' THEN
    SELECT r.allowed, r.reason INTO v_allowed, v_reason
    FROM ig_check_and_increment_rate_limit(p_account_id, 25) r;

    SELECT COALESCE(t.daily_count, 0) INTO v_daily
    FROM ig_rate_limit_tracking t WHERE t.account_id = p_account_id;

    RETURN QUERY SELECT v_allowed, v_reason, COALESCE(v_daily, 0)::INT, 25;
  ELSE
    SELECT r.allowed, r.reason, r.posts_today INTO v_allowed, v_reason, v_daily
    FROM check_and_increment_rate_limit(p_account_id, 25, 200) r;

    RETURN QUERY SELECT v_allowed, v_reason, COALESCE(v_daily, 0)::INT, 200;
  END IF;
END;
$$;

-- ============================================================================
-- 7. Grants
-- ============================================================================

GRANT EXECUTE ON FUNCTION check_and_increment_rate_limit(UUID, INTEGER, INTEGER) TO service_role;
GRANT EXECUTE ON FUNCTION get_rate_limit_status(UUID) TO service_role;
GRANT EXECUTE ON FUNCTION ig_check_and_increment_rate_limit(UUID, INTEGER) TO service_role;
GRANT EXECUTE ON FUNCTION check_publish_rate_limit(UUID, TEXT) TO service_role;
GRANT ALL ON TABLE rate_limit_tracking TO service_role;
GRANT ALL ON TABLE ig_rate_limit_tracking TO service_role;

-- ============================================================================
-- 8. RLS on rate limit tables
-- ============================================================================

ALTER TABLE rate_limit_tracking ENABLE ROW LEVEL SECURITY;
ALTER TABLE ig_rate_limit_tracking ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Service role rate_limit_tracking" ON rate_limit_tracking;
CREATE POLICY "Service role rate_limit_tracking" ON rate_limit_tracking FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "Service role ig_rate_limit_tracking" ON ig_rate_limit_tracking;
CREATE POLICY "Service role ig_rate_limit_tracking" ON ig_rate_limit_tracking FOR ALL TO service_role USING (true) WITH CHECK (true);

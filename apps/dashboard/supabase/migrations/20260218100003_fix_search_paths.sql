-- Fix mutable search_path warnings from Supabase database linter

BEGIN;

-- 1. check_publish_rate_limit
CREATE OR REPLACE FUNCTION check_publish_rate_limit(
  p_account_id UUID,
  p_platform TEXT DEFAULT 'threads'
) RETURNS TABLE(allowed BOOLEAN, reason TEXT, daily_used INT, daily_limit INT)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_allowed BOOLEAN;
  v_reason TEXT;
  v_daily INT;
  v_hourly INT;
BEGIN
  IF p_platform = 'instagram' THEN
    SELECT r.allowed, r.reason
    INTO v_allowed, v_reason
    FROM ig_check_and_increment_rate_limit(p_account_id, 25) r;

    SELECT COALESCE(daily_count, 0)
    INTO v_daily
    FROM ig_rate_limit_tracking
    WHERE account_id = p_account_id;

    RETURN QUERY SELECT v_allowed, v_reason, COALESCE(v_daily, 0)::INT, 25;
  ELSE
    SELECT r.allowed, r.reason, r.posts_today
    INTO v_allowed, v_reason, v_daily
    FROM check_and_increment_rate_limit(p_account_id, 25, 200) r;

    RETURN QUERY SELECT v_allowed, v_reason, COALESCE(v_daily, 0)::INT, 200;
  END IF;
END;
$$;

GRANT EXECUTE ON FUNCTION check_publish_rate_limit TO service_role;

-- 2. cleanup_old_cron_runs
CREATE OR REPLACE FUNCTION cleanup_old_cron_runs(p_retention_days INT DEFAULT 30)
RETURNS INT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_deleted INT;
BEGIN
  DELETE FROM cron_runs
  WHERE started_at < NOW() - (p_retention_days || ' days')::INTERVAL;
  GET DIAGNOSTICS v_deleted = ROW_COUNT;
  RETURN v_deleted;
END;
$$;

GRANT EXECUTE ON FUNCTION cleanup_old_cron_runs TO service_role;

COMMIT;

-- Fix Instagram rate limit in check_publish_rate_limit()
-- The IG daily limit was hardcoded to 25 instead of 50.

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
    FROM ig_check_and_increment_rate_limit(p_account_id, 50) r;

    SELECT COALESCE(t.daily_count, 0) INTO v_daily
    FROM ig_rate_limit_tracking t WHERE t.account_id = p_account_id;

    RETURN QUERY SELECT v_allowed, v_reason, COALESCE(v_daily, 0)::INT, 50;
  ELSE
    SELECT r.allowed, r.reason, r.posts_today INTO v_allowed, v_reason, v_daily
    FROM check_and_increment_rate_limit(p_account_id, 25, 200) r;

    RETURN QUERY SELECT v_allowed, v_reason, COALESCE(v_daily, 0)::INT, 200;
  END IF;
END;
$$;

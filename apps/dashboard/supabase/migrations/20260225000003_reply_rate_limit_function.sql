-- Atomic rate limit check for replies (prevents race conditions)
CREATE OR REPLACE FUNCTION check_reply_rate_limit(
  p_account_id TEXT,
  p_hourly_limit INTEGER DEFAULT 55,
  p_daily_limit INTEGER DEFAULT 480
)
RETURNS JSON AS $$
DECLARE
  v_hourly_count INTEGER;
  v_daily_count INTEGER;
  v_one_hour_ago TIMESTAMPTZ := NOW() - INTERVAL '1 hour';
  v_start_of_day TIMESTAMPTZ := DATE_TRUNC('day', NOW());
BEGIN
  -- Lock the account's sent_replies rows to prevent concurrent checks
  PERFORM 1 FROM sent_replies
    WHERE account_id = p_account_id
    AND created_at >= v_start_of_day
    FOR UPDATE SKIP LOCKED;

  SELECT COUNT(*) INTO v_hourly_count
  FROM sent_replies
  WHERE account_id = p_account_id
    AND created_at >= v_one_hour_ago;

  SELECT COUNT(*) INTO v_daily_count
  FROM sent_replies
  WHERE account_id = p_account_id
    AND created_at >= v_start_of_day;

  IF v_hourly_count >= p_hourly_limit THEN
    RETURN json_build_object(
      'allowed', false,
      'reason', format('Rate limit: Too many replies this hour (%s/%s).', v_hourly_count, p_hourly_limit)
    );
  END IF;

  IF v_daily_count >= p_daily_limit THEN
    RETURN json_build_object(
      'allowed', false,
      'reason', format('Rate limit: Too many replies today (%s/%s).', v_daily_count, p_daily_limit)
    );
  END IF;

  RETURN json_build_object('allowed', true);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public;

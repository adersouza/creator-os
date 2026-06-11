-- Update Instagram rate limit from 25/day to 50/day
-- Instagram's content publishing limit is 50 posts per 24-hour period

ALTER TABLE ig_rate_limit_tracking
ADD COLUMN IF NOT EXISTS last_reset_at TIMESTAMPTZ DEFAULT NOW();

DROP FUNCTION IF EXISTS ig_check_and_increment_rate_limit(UUID, INTEGER);

CREATE OR REPLACE FUNCTION ig_check_and_increment_rate_limit(
  p_account_id UUID,
  p_daily_limit INTEGER DEFAULT 50
)
RETURNS TABLE(allowed BOOLEAN, reason TEXT)
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  v_daily_count INTEGER;
BEGIN
  -- Lock the row for this account to prevent race conditions
  PERFORM 1 FROM ig_rate_limit_tracking
  WHERE account_id = p_account_id
  FOR UPDATE;

  -- Get or create tracking record
  INSERT INTO ig_rate_limit_tracking (account_id, daily_count, last_reset_at)
  VALUES (p_account_id, 0, NOW())
  ON CONFLICT (account_id) DO NOTHING;

  -- Reset daily counter if last reset was more than 24 hours ago
  UPDATE ig_rate_limit_tracking
  SET daily_count = 0, last_reset_at = NOW()
  WHERE account_id = p_account_id
    AND last_reset_at < NOW() - INTERVAL '24 hours';

  -- Get current count
  SELECT daily_count INTO v_daily_count
  FROM ig_rate_limit_tracking
  WHERE account_id = p_account_id;

  -- Check limit
  IF v_daily_count >= p_daily_limit THEN
    RETURN QUERY SELECT FALSE, FORMAT('Daily limit reached (%s/%s)', v_daily_count, p_daily_limit);
    RETURN;
  END IF;

  -- Increment counter
  UPDATE ig_rate_limit_tracking
  SET daily_count = daily_count + 1
  WHERE account_id = p_account_id;

  RETURN QUERY SELECT TRUE, NULL::TEXT;
END;
$$;

-- Repair get_rate_limit_status after rate_limit_tracking column rename.

CREATE OR REPLACE FUNCTION public.get_rate_limit_status(
  p_account_id TEXT,
  p_hourly_limit INTEGER DEFAULT 25,
  p_daily_limit INTEGER DEFAULT 250
) RETURNS TABLE(
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
  v_hourly INTEGER := 0;
  v_daily INTEGER := 0;
  v_hour_start TIMESTAMPTZ;
  v_day_start TIMESTAMPTZ;
BEGIN
  SELECT *
    INTO v_record
    FROM public.rate_limit_tracking
    WHERE account_id = p_account_id;

  IF NOT FOUND THEN
    RETURN QUERY SELECT
      0,
      0,
      p_hourly_limit,
      p_daily_limit,
      v_now + INTERVAL '1 hour',
      (v_today + 1)::TIMESTAMPTZ;
    RETURN;
  END IF;

  v_hour_start := COALESCE(v_record.hour_window_start, v_now);
  v_day_start := COALESCE(v_record.day_window_start, v_now);
  v_hourly := COALESCE(v_record.posts_this_hour, 0);
  v_daily := COALESCE(v_record.posts_today, 0);

  IF v_hour_start < v_hour_ago THEN
    v_hourly := 0;
  END IF;

  IF v_day_start::DATE < v_today THEN
    v_daily := 0;
  END IF;

  RETURN QUERY SELECT
    v_hourly,
    v_daily,
    GREATEST(0, p_hourly_limit - v_hourly),
    GREATEST(0, p_daily_limit - v_daily),
    v_hour_start + INTERVAL '1 hour',
    (v_day_start::DATE + 1)::TIMESTAMPTZ;
END;
$$;

GRANT EXECUTE ON FUNCTION public.get_rate_limit_status(TEXT, INTEGER, INTEGER)
  TO authenticated, service_role;

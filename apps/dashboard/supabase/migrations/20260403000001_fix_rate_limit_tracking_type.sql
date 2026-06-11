-- Migration: Fix rate_limit_tracking FK type mismatch
-- Date: 2026-04-03
-- Purpose: accounts.id is TEXT but rate_limit_tracking.account_id was defined as UUID.
--          This migration corrects the column type to TEXT to match the FK target.

DO $$
BEGIN
  -- Only alter if the table exists
  IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = 'rate_limit_tracking'
  ) THEN
    -- Drop the FK constraint first (it references accounts.id which is TEXT)
    IF EXISTS (
      SELECT 1 FROM information_schema.table_constraints
      WHERE table_name = 'rate_limit_tracking'
        AND constraint_type = 'FOREIGN KEY'
        AND constraint_name LIKE '%account_id%'
    ) THEN
      EXECUTE (
        SELECT 'ALTER TABLE public.rate_limit_tracking DROP CONSTRAINT ' || constraint_name
        FROM information_schema.table_constraints
        WHERE table_name = 'rate_limit_tracking'
          AND constraint_type = 'FOREIGN KEY'
          AND constraint_name LIKE '%account_id%'
        LIMIT 1
      );
    END IF;

    -- Change column type from UUID to TEXT
    ALTER TABLE public.rate_limit_tracking
      ALTER COLUMN account_id TYPE TEXT USING account_id::TEXT;

    -- Re-add the FK constraint
    ALTER TABLE public.rate_limit_tracking
      ADD CONSTRAINT rate_limit_tracking_account_id_fkey
      FOREIGN KEY (account_id) REFERENCES public.accounts(id) ON DELETE CASCADE;

    -- Also fix the function signatures from UUID to TEXT
    DROP FUNCTION IF EXISTS check_and_increment_rate_limit(UUID, INTEGER, INTEGER);
    DROP FUNCTION IF EXISTS get_rate_limit_status(UUID);

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
    AS $fn$
    DECLARE
      v_record rate_limit_tracking%ROWTYPE;
      v_now TIMESTAMPTZ := NOW();
      v_today DATE := CURRENT_DATE;
      v_hour_ago TIMESTAMPTZ := v_now - INTERVAL '1 hour';
    BEGIN
      INSERT INTO rate_limit_tracking (account_id, posts_this_hour, posts_today, hour_window_start, day_window_start)
      VALUES (p_account_id, 0, 0, v_now, v_today::TIMESTAMPTZ)
      ON CONFLICT (account_id) DO UPDATE
      SET updated_at = v_now
      RETURNING * INTO v_record;

      SELECT * INTO v_record
      FROM rate_limit_tracking
      WHERE account_id = p_account_id
      FOR UPDATE;

      IF v_record.hour_window_start < v_hour_ago THEN
        v_record.posts_this_hour := 0;
        v_record.hour_window_start := v_now;
      END IF;

      IF v_record.day_window_start::DATE < v_today THEN
        v_record.posts_today := 0;
        v_record.day_window_start := v_today::TIMESTAMPTZ;
      END IF;

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

      UPDATE rate_limit_tracking
      SET
        posts_this_hour = v_record.posts_this_hour + 1,
        posts_today = v_record.posts_today + 1,
        hour_window_start = v_record.hour_window_start,
        day_window_start = v_record.day_window_start,
        last_post_at = v_now,
        updated_at = v_now
      WHERE account_id = p_account_id;

      RETURN QUERY SELECT
        TRUE,
        NULL::TEXT,
        v_record.posts_this_hour + 1,
        v_record.posts_today + 1;
    END;
    $fn$;

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
    AS $fn$
    DECLARE
      v_record rate_limit_tracking%ROWTYPE;
      v_now TIMESTAMPTZ := NOW();
      v_today DATE := CURRENT_DATE;
      v_hour_ago TIMESTAMPTZ := v_now - INTERVAL '1 hour';
      v_hourly_limit INTEGER := 3;
      v_daily_limit INTEGER := 20;
    BEGIN
      SELECT * INTO v_record
      FROM rate_limit_tracking
      WHERE account_id = p_account_id;

      IF v_record IS NULL THEN
        RETURN QUERY SELECT
          0, 0,
          v_hourly_limit, v_daily_limit,
          v_now + INTERVAL '1 hour',
          (v_today + 1)::TIMESTAMPTZ;
        RETURN;
      END IF;

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
    $fn$;

    GRANT EXECUTE ON FUNCTION check_and_increment_rate_limit(TEXT, INTEGER, INTEGER) TO service_role;
    GRANT EXECUTE ON FUNCTION get_rate_limit_status(TEXT) TO service_role;
  END IF;
END;
$$;

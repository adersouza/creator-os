-- ============================================================================
-- DB security + performance polish
-- ============================================================================
-- Date: 2026-05-05
-- Items addressed:
--   1. auth_rls_initplan — 5 policies using auth.uid()/jwt() without SELECT wrapper
--   2. function_search_path_mutable — 3 functions missing SET search_path
--   3. rls_policy_always_true — 4 always-true PUBLIC policies (should be service_role)
--   4. unindexed_foreign_keys — content_collections + saved_nl_queries user_id
-- ============================================================================

BEGIN;

-- ============================================================================
-- 1. auth_rls_initplan: wrap auth.uid() / auth.jwt() in (SELECT ...) so Postgres
--    evaluates them once per query instead of once per row.
-- ============================================================================

ALTER POLICY "Users view own account health signals"
  ON public.account_health_signals
  USING (EXISTS (
    SELECT 1 FROM accounts a
    WHERE a.id = account_health_signals.account_id
      AND a.user_id = ((SELECT auth.uid()))::text
  ));

ALTER POLICY "Users manage own reschedule log"
  ON public.calendar_reschedule_log
  USING (((SELECT auth.uid()))::text = user_id)
  WITH CHECK (((SELECT auth.uid()))::text = user_id);

ALTER POLICY "Users view own portfolio health"
  ON public.portfolio_account_health
  USING (((SELECT auth.uid()))::text = user_id);

ALTER POLICY "Service role manages health"
  ON public.portfolio_account_health
  USING ((SELECT (auth.jwt() ->> 'role'::text)) = 'service_role'::text)
  WITH CHECK ((SELECT (auth.jwt() ->> 'role'::text)) = 'service_role'::text);

ALTER POLICY "Service role manages report send log"
  ON public.report_send_log
  USING ((SELECT (auth.jwt() ->> 'role'::text)) = 'service_role'::text)
  WITH CHECK ((SELECT (auth.jwt() ->> 'role'::text)) = 'service_role'::text);

-- ============================================================================
-- 2. function_search_path_mutable: add SET search_path to prevent schema injection.
-- ============================================================================

-- Trigger function — no table references, empty search_path is safe
CREATE OR REPLACE FUNCTION public.set_saved_views_updated_at()
  RETURNS trigger
  LANGUAGE plpgsql
  SET search_path = ''
AS $function$
BEGIN
  NEW.updated_at := NOW();
  RETURN NEW;
END;
$function$;

-- Rate limit status (single-param) — references rate_limit_tracking unqualified
CREATE OR REPLACE FUNCTION public.get_rate_limit_status(p_account_id text)
  RETURNS TABLE(
    posts_this_hour integer,
    posts_today integer,
    hourly_remaining integer,
    daily_remaining integer,
    next_hour_reset timestamp with time zone,
    next_day_reset timestamp with time zone
  )
  LANGUAGE plpgsql
  SET search_path = public
AS $function$
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
$function$;

-- Rate limit check+increment — references rate_limit_tracking and its %ROWTYPE
CREATE OR REPLACE FUNCTION public.check_and_increment_rate_limit(
  p_account_id text,
  p_hourly_limit integer DEFAULT 3,
  p_daily_limit integer DEFAULT 20
)
  RETURNS TABLE(allowed boolean, reason text, posts_this_hour integer, posts_today integer)
  LANGUAGE plpgsql
  SET search_path = public
AS $function$
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
$function$;

-- ============================================================================
-- 3. rls_policy_always_true: scope always-true PUBLIC policies to service_role.
--    service_role bypasses RLS entirely, so these remain functional for backend.
--    Without the fix, anon/authenticated also get unrestricted row access.
-- ============================================================================

ALTER POLICY "Service can manage follower history"
  ON public.follower_history
  USING ((SELECT (auth.jwt() ->> 'role'::text)) = 'service_role'::text)
  WITH CHECK ((SELECT (auth.jwt() ->> 'role'::text)) = 'service_role'::text);

ALTER POLICY "link_page_variants_service_insert"
  ON public.link_page_variants
  WITH CHECK ((SELECT (auth.jwt() ->> 'role'::text)) = 'service_role'::text);

ALTER POLICY "link_page_variants_service_update"
  ON public.link_page_variants
  USING ((SELECT (auth.jwt() ->> 'role'::text)) = 'service_role'::text)
  WITH CHECK ((SELECT (auth.jwt() ->> 'role'::text)) = 'service_role'::text);

ALTER POLICY "Service can manage reply times"
  ON public.reply_response_times
  USING ((SELECT (auth.jwt() ->> 'role'::text)) = 'service_role'::text)
  WITH CHECK ((SELECT (auth.jwt() ->> 'role'::text)) = 'service_role'::text);

-- ============================================================================
-- 4. unindexed_foreign_keys: two new tables missing user_id indexes.
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_content_collections_user_id
  ON public.content_collections (user_id);

CREATE INDEX IF NOT EXISTS idx_saved_nl_queries_user_id
  ON public.saved_nl_queries (user_id);

COMMIT;

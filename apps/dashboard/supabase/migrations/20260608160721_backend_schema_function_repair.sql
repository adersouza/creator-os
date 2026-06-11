BEGIN;

-- The beta claim RPC and checkout flow both depend on this profile field.
ALTER TABLE IF EXISTS public.profiles
  ADD COLUMN IF NOT EXISTS beta_discount_code TEXT;

CREATE OR REPLACE FUNCTION public.increment_dm_template_use(
  p_template_id TEXT,
  p_user_id TEXT
)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  IF to_regclass('public.ig_dm_templates') IS NULL THEN
    RETURN;
  END IF;

  UPDATE public.ig_dm_templates
  SET
    use_count = COALESCE(use_count, 0) + 1,
    updated_at = now()
  WHERE id = p_template_id
    AND user_id = p_user_id;
END;
$$;

DROP FUNCTION IF EXISTS public.increment_dm_template_use(UUID, UUID);

CREATE OR REPLACE FUNCTION public.increment_ai_generations(
  p_workspace_id TEXT,
  p_count INT,
  p_today DATE,
  p_reset BOOLEAN DEFAULT FALSE,
  p_limit INT DEFAULT 0
)
RETURNS INT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_current INT := 0;
  v_last_generation_date DATE;
  v_allowed INT;
BEGIN
  IF to_regclass('public.auto_post_config') IS NULL THEN
    RETURN 0;
  END IF;

  SELECT
    COALESCE(ai_generations_today, 0),
    ai_last_generation_date
  INTO v_current, v_last_generation_date
  FROM public.auto_post_config
  WHERE workspace_id = p_workspace_id
  FOR UPDATE;

  IF NOT FOUND THEN
    RETURN 0;
  END IF;

  IF p_reset OR v_last_generation_date IS DISTINCT FROM p_today THEN
    v_current := 0;
  END IF;

  IF p_limit > 0 THEN
    v_allowed := LEAST(p_count, GREATEST(p_limit - v_current, 0));
  ELSE
    v_allowed := p_count;
  END IF;

  UPDATE public.auto_post_config
  SET
    ai_generations_today = v_current + v_allowed,
    ai_last_generation_date = p_today
  WHERE workspace_id = p_workspace_id;

  RETURN v_allowed;
END;
$$;

CREATE OR REPLACE FUNCTION public.classify_account_cohorts()
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_threads_count INTEGER := 0;
  v_instagram_count INTEGER := 0;
BEGIN
  IF to_regclass('public.accounts') IS NULL
    OR to_regclass('public.instagram_accounts') IS NULL
    OR to_regclass('public.posts') IS NULL
  THEN
    RETURN 0;
  END IF;

  WITH post_activity AS (
    SELECT
      account_id,
      BOOL_OR(published_at > NOW() - INTERVAL '24 hours') AS posted_24h,
      BOOL_OR(published_at > NOW() - INTERVAL '7 days') AS posted_7d,
      BOOL_OR(published_at > NOW() - INTERVAL '30 days') AS posted_30d
    FROM public.posts
    WHERE status = 'published'
      AND account_id IS NOT NULL
      AND published_at > NOW() - INTERVAL '30 days'
    GROUP BY account_id
  ),
  desired AS (
    SELECT
      a.id,
      CASE
        WHEN COALESCE(a.followers_count, 0) >= 500
          OR COALESCE(pa.posted_24h, FALSE)
          OR a.last_synced_at > NOW() - INTERVAL '2 hours'
          THEN 'hot'
        WHEN COALESCE(pa.posted_7d, FALSE) THEN 'warm'
        WHEN COALESCE(pa.posted_30d, FALSE) THEN 'cold'
        ELSE 'dormant'
      END AS sync_cohort
    FROM public.accounts a
    LEFT JOIN post_activity pa ON pa.account_id = a.id
    WHERE a.threads_access_token_encrypted IS NOT NULL
  ),
  updated AS (
    UPDATE public.accounts a
    SET
      sync_cohort = d.sync_cohort,
      cohort_updated_at = NOW()
    FROM desired d
    WHERE a.id = d.id
      AND (
        a.sync_cohort IS DISTINCT FROM d.sync_cohort
        OR a.cohort_updated_at IS NULL
        OR a.cohort_updated_at < NOW() - INTERVAL '6 hours'
      )
    RETURNING 1
  )
  SELECT COUNT(*) INTO v_threads_count FROM updated;

  WITH post_activity AS (
    SELECT
      instagram_account_id,
      BOOL_OR(published_at > NOW() - INTERVAL '24 hours') AS posted_24h,
      BOOL_OR(published_at > NOW() - INTERVAL '7 days') AS posted_7d,
      BOOL_OR(published_at > NOW() - INTERVAL '30 days') AS posted_30d
    FROM public.posts
    WHERE status = 'published'
      AND platform = 'instagram'
      AND instagram_account_id IS NOT NULL
      AND published_at > NOW() - INTERVAL '30 days'
    GROUP BY instagram_account_id
  ),
  desired AS (
    SELECT
      ia.id,
      CASE
        WHEN COALESCE(ia.follower_count, 0) >= 500
          OR COALESCE(pa.posted_24h, FALSE)
          OR ia.last_synced_at > NOW() - INTERVAL '2 hours'
          THEN 'hot'
        WHEN COALESCE(pa.posted_7d, FALSE) THEN 'warm'
        WHEN COALESCE(pa.posted_30d, FALSE) THEN 'cold'
        ELSE 'dormant'
      END AS sync_cohort
    FROM public.instagram_accounts ia
    LEFT JOIN post_activity pa ON pa.instagram_account_id = ia.id
    WHERE ia.instagram_access_token_encrypted IS NOT NULL
  ),
  updated AS (
    UPDATE public.instagram_accounts ia
    SET
      sync_cohort = d.sync_cohort,
      cohort_updated_at = NOW()
    FROM desired d
    WHERE ia.id = d.id
      AND (
        ia.sync_cohort IS DISTINCT FROM d.sync_cohort
        OR ia.cohort_updated_at IS NULL
        OR ia.cohort_updated_at < NOW() - INTERVAL '6 hours'
      )
    RETURNING 1
  )
  SELECT COUNT(*) INTO v_instagram_count FROM updated;

  RETURN v_threads_count + v_instagram_count;
END;
$$;

CREATE OR REPLACE FUNCTION public.refresh_group_analytics(
  p_user_id TEXT,
  p_date DATE DEFAULT CURRENT_DATE
)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_group RECORD;
  v_count INTEGER := 0;
  v_account_ids TEXT[];
  v_stats RECORD;
  v_prev_followers INTEGER;
  v_top_account TEXT;
BEGIN
  IF to_regclass('public.account_groups') IS NULL
    OR to_regclass('public.account_analytics') IS NULL
    OR to_regclass('public.group_analytics') IS NULL
  THEN
    RETURN 0;
  END IF;

  FOR v_group IN
    SELECT id, account_ids
    FROM public.account_groups
    WHERE user_id = p_user_id
      AND account_ids IS NOT NULL
      AND array_length(account_ids, 1) > 0
  LOOP
    v_account_ids := v_group.account_ids::TEXT[];

    SELECT
      COALESCE(SUM(aa.followers_count), 0) AS total_followers,
      COALESCE(SUM(aa.total_views), 0) AS total_views,
      COALESCE(SUM(aa.total_likes), 0) AS total_likes,
      COALESCE(SUM(aa.total_replies), 0) AS total_replies,
      COALESCE(SUM(aa.total_reposts), 0) AS total_reposts,
      COALESCE(SUM(aa.total_quotes), 0) AS total_quotes,
      COALESCE(SUM(aa.posts_count), 0) AS posts_count,
      COUNT(DISTINCT aa.account_id) AS accounts_count,
      CASE
        WHEN SUM(aa.total_views) > 0 THEN
          (SUM(aa.total_likes) + SUM(aa.total_replies) + SUM(aa.total_reposts))::DECIMAL
          / SUM(aa.total_views) * 100
        ELSE 0
      END AS avg_engagement_rate
    INTO v_stats
    FROM public.account_analytics aa
    WHERE aa.account_id::TEXT = ANY(v_account_ids)
      AND aa.date = p_date;

    SELECT COALESCE(total_followers, 0)
    INTO v_prev_followers
    FROM public.group_analytics
    WHERE group_id = v_group.id
      AND date = p_date - 1;

    SELECT aa.account_id::TEXT
    INTO v_top_account
    FROM public.account_analytics aa
    WHERE aa.account_id::TEXT = ANY(v_account_ids)
      AND aa.date = p_date
      AND aa.total_views > 0
    ORDER BY (aa.total_likes + aa.total_replies + aa.total_reposts)::DECIMAL / aa.total_views DESC
    LIMIT 1;

    INSERT INTO public.group_analytics (
      group_id,
      user_id,
      date,
      total_followers,
      total_views,
      total_likes,
      total_replies,
      total_reposts,
      total_quotes,
      posts_count,
      accounts_count,
      avg_engagement_rate,
      follower_growth,
      top_performing_account_id,
      updated_at
    ) VALUES (
      v_group.id,
      p_user_id,
      p_date,
      v_stats.total_followers,
      v_stats.total_views,
      v_stats.total_likes,
      v_stats.total_replies,
      v_stats.total_reposts,
      v_stats.total_quotes,
      v_stats.posts_count,
      v_stats.accounts_count,
      v_stats.avg_engagement_rate,
      v_stats.total_followers - COALESCE(v_prev_followers, v_stats.total_followers),
      v_top_account,
      NOW()
    )
    ON CONFLICT (group_id, date) DO UPDATE SET
      total_followers = EXCLUDED.total_followers,
      total_views = EXCLUDED.total_views,
      total_likes = EXCLUDED.total_likes,
      total_replies = EXCLUDED.total_replies,
      total_reposts = EXCLUDED.total_reposts,
      total_quotes = EXCLUDED.total_quotes,
      posts_count = EXCLUDED.posts_count,
      accounts_count = EXCLUDED.accounts_count,
      avg_engagement_rate = EXCLUDED.avg_engagement_rate,
      follower_growth = EXCLUDED.follower_growth,
      top_performing_account_id = EXCLUDED.top_performing_account_id,
      updated_at = NOW();

    v_count := v_count + 1;
  END LOOP;

  RETURN v_count;
END;
$$;

CREATE OR REPLACE FUNCTION public.mark_reply_as_read(p_reply_id TEXT)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_post_owner_id TEXT;
  v_current_user_id TEXT;
BEGIN
  IF to_regclass('public.post_replies') IS NULL
    OR to_regclass('public.posts') IS NULL
  THEN
    RETURN FALSE;
  END IF;

  v_current_user_id := auth.uid()::text;

  IF v_current_user_id IS NULL THEN
    RAISE EXCEPTION 'Not authenticated';
  END IF;

  SELECT p.user_id
  INTO v_post_owner_id
  FROM public.post_replies pr
  JOIN public.posts p ON p.id = pr.post_id
  WHERE pr.id = p_reply_id;

  IF v_post_owner_id IS NULL THEN
    RAISE EXCEPTION 'Reply not found';
  END IF;

  IF v_post_owner_id != v_current_user_id THEN
    RAISE EXCEPTION 'Not authorized to mark this reply as read';
  END IF;

  UPDATE public.post_replies
  SET is_read = true
  WHERE id = p_reply_id;

  RETURN TRUE;
END;
$$;

CREATE OR REPLACE FUNCTION public.mark_all_replies_as_read(p_post_id TEXT DEFAULT NULL)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_current_user_id TEXT;
  v_updated_count INTEGER;
BEGIN
  IF to_regclass('public.post_replies') IS NULL
    OR to_regclass('public.posts') IS NULL
  THEN
    RETURN 0;
  END IF;

  v_current_user_id := auth.uid()::text;

  IF v_current_user_id IS NULL THEN
    RAISE EXCEPTION 'Not authenticated';
  END IF;

  IF p_post_id IS NOT NULL THEN
    UPDATE public.post_replies pr
    SET is_read = true
    FROM public.posts p
    WHERE pr.post_id = p.id
      AND p.user_id = v_current_user_id
      AND p.id = p_post_id
      AND pr.is_read = false;
  ELSE
    UPDATE public.post_replies pr
    SET is_read = true
    FROM public.posts p
    WHERE pr.post_id = p.id
      AND p.user_id = v_current_user_id
      AND pr.is_read = false;
  END IF;

  GET DIAGNOSTICS v_updated_count = ROW_COUNT;
  RETURN v_updated_count;
END;
$$;

DROP FUNCTION IF EXISTS public.mark_reply_as_read(UUID);
DROP FUNCTION IF EXISTS public.mark_all_replies_as_read(UUID);

DO $$
DECLARE
  function_signature TEXT;
  function_regprocedure REGPROCEDURE;
BEGIN
  FOREACH function_signature IN ARRAY ARRAY[
    'public.increment_dm_template_use(text, text)',
    'public.increment_ai_generations(text, integer, date, boolean, integer)',
    'public.classify_account_cohorts()',
    'public.refresh_group_analytics(text, date)',
    'public.mark_reply_as_read(text)',
    'public.mark_all_replies_as_read(text)'
  ]
  LOOP
    function_regprocedure := to_regprocedure(function_signature);

    IF function_regprocedure IS NOT NULL THEN
      EXECUTE format(
        'REVOKE EXECUTE ON FUNCTION %s FROM PUBLIC, anon, authenticated',
        function_regprocedure
      );
      EXECUTE format(
        'GRANT EXECUTE ON FUNCTION %s TO service_role',
        function_regprocedure
      );
    END IF;
  END LOOP;
END $$;

DROP POLICY IF EXISTS "Users view own instagram account restriction events" ON public.instagram_account_restriction_events;
DO $$
BEGIN
  IF to_regclass('public.instagram_account_restriction_events') IS NOT NULL
    AND NOT EXISTS (
      SELECT 1
      FROM pg_policies
      WHERE schemaname = 'public'
        AND tablename = 'instagram_account_restriction_events'
        AND policyname = 'Users view own instagram account restriction events'
    )
  THEN
    CREATE POLICY "Users view own instagram account restriction events"
      ON public.instagram_account_restriction_events
      FOR SELECT
      TO authenticated
      USING (user_id = (select auth.uid())::text);
  END IF;
END $$;

DROP POLICY IF EXISTS "Service role manages instagram account restriction events" ON public.instagram_account_restriction_events;
DO $$
BEGIN
  IF to_regclass('public.instagram_account_restriction_events') IS NOT NULL
    AND NOT EXISTS (
      SELECT 1
      FROM pg_policies
      WHERE schemaname = 'public'
        AND tablename = 'instagram_account_restriction_events'
        AND policyname = 'Service role manages instagram account restriction events'
    )
  THEN
    CREATE POLICY "Service role manages instagram account restriction events"
      ON public.instagram_account_restriction_events
      FOR ALL
      TO service_role
      USING (true)
      WITH CHECK (true);
  END IF;
END $$;

COMMIT;

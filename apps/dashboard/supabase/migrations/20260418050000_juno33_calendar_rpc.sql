-- juno33 Calendar RPC — collapses useCalendarPosts's 7 parallel + 2
-- sequential fallback queries into a single round-trip.
--
-- The hook needs: weekly posts joined to owning accounts + groups, all
-- future scheduled posts bucketed by group for queue-health, and the
-- 48h gap count. Every slice is scoped by (SELECT auth.uid()) so RLS
-- enforces tenant isolation.

CREATE OR REPLACE FUNCTION public.get_calendar_week(
  p_week_start timestamptz,
  p_gap_window_hours int DEFAULT 48,
  p_target_posts_per_day int DEFAULT 3
)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY INVOKER
SET search_path = public, pg_catalog
AS $$
DECLARE
  v_user text := (SELECT auth.uid()::text);
  v_now timestamptz := now();
  v_week_end timestamptz := p_week_start + interval '7 days';
  v_gap_end timestamptz := v_now + make_interval(hours => p_gap_window_hours);
  v_posts jsonb;
  v_groups jsonb;
  v_queue_health jsonb;
  v_gaps_count int;
  v_total_queue bigint;
  v_unassigned_count int;
BEGIN
  IF v_user IS NULL THEN
    RETURN jsonb_build_object(
      'posts', '[]'::jsonb,
      'groups', '[]'::jsonb,
      'queueHealthByGroup', '{}'::jsonb,
      'gapsCount', 0,
      'totalQueue', 0
    );
  END IF;

  -- ── 1. Weekly posts (scheduled in window OR published in window) ────────
  WITH week_posts AS (
    SELECT DISTINCT ON (p.id)
      p.id,
      p.content,
      p.media_urls,
      p.status,
      p.approval_status,
      p.scheduled_for,
      p.published_at,
      p.platform,
      p.account_id,
      p.instagram_account_id
    FROM public.posts p
    WHERE p.user_id = v_user
      AND (
        (p.scheduled_for >= p_week_start AND p.scheduled_for < v_week_end)
        OR (p.status = 'published' AND p.published_at >= p_week_start AND p.published_at < v_week_end)
      )
  ),
  joined AS (
    SELECT
      wp.*,
      coalesce(ta.id, ia.id::text) AS resolved_account_id,
      coalesce(ta.username, ia.username) AS username,
      coalesce(ta.display_name, ia.display_name) AS display_name,
      coalesce(ta.group_id, ia.group_id) AS group_id
    FROM week_posts wp
    LEFT JOIN public.accounts ta
      ON ta.id = wp.account_id AND ta.user_id = v_user
      AND (wp.platform = 'threads' OR (wp.platform IS NULL AND wp.account_id IS NOT NULL))
    LEFT JOIN public.instagram_accounts ia
      ON ia.id = wp.instagram_account_id AND ia.user_id = v_user
      AND (wp.platform = 'instagram' OR (wp.platform IS NULL AND wp.instagram_account_id IS NOT NULL))
  )
  SELECT coalesce(
    jsonb_agg(
      jsonb_build_object(
        'id', j.id,
        'content', coalesce(j.content, ''),
        'media_urls', coalesce(j.media_urls, ARRAY[]::text[]),
        'status', j.status,
        'approval_status', j.approval_status,
        'scheduled_for', j.scheduled_for,
        'published_at', j.published_at,
        'platform', j.platform,
        'account_id', j.resolved_account_id,
        'username', j.username,
        'display_name', j.display_name,
        'group_id', j.group_id,
        'group_name', g.name,
        'group_color', coalesce(nullif(g.color, ''), '#6B6B70')
      )
    ),
    '[]'::jsonb
  )
  INTO v_posts
  FROM joined j
  LEFT JOIN public.account_groups g ON g.id = j.group_id AND g.user_id = v_user;

  -- ── 2. Groups (all user groups, sorted by name) ─────────────────────────
  SELECT coalesce(
    jsonb_agg(
      jsonb_build_object(
        'id', id,
        'name', name,
        'color', coalesce(nullif(color, ''), '#6B6B70')
      ) ORDER BY name ASC
    ),
    '[]'::jsonb
  )
  INTO v_groups
  FROM public.account_groups
  WHERE user_id = v_user;

  -- ── 3. Queue health: all future scheduled posts bucketed by group ───────
  WITH future_scheduled AS (
    SELECT p.account_id, p.instagram_account_id, p.platform
    FROM public.posts p
    WHERE p.user_id = v_user
      AND p.status = 'scheduled'
      AND p.scheduled_for >= v_now
  ),
  bucketed AS (
    SELECT
      coalesce(ta.group_id, ia.group_id) AS group_id
    FROM future_scheduled fs
    LEFT JOIN public.accounts ta
      ON ta.id = fs.account_id AND ta.user_id = v_user AND fs.platform = 'threads'
    LEFT JOIN public.instagram_accounts ia
      ON ia.id = fs.instagram_account_id AND ia.user_id = v_user AND fs.platform = 'instagram'
  ),
  group_counts AS (
    SELECT coalesce(group_id::text, 'unassigned') AS bucket, count(*)::int AS count
    FROM bucketed
    GROUP BY bucket
  )
  SELECT
    coalesce(
      jsonb_object_agg(
        gc.bucket,
        jsonb_build_object(
          'id', gc.bucket,
          'name', coalesce(g.name, 'Unassigned'),
          'color', coalesce(nullif(g.color, ''), '#6B6B70'),
          'postsCount', gc.count,
          'daysOfContent', round((gc.count::numeric / p_target_posts_per_day::numeric) * 10) / 10
        )
      ),
      '{}'::jsonb
    ),
    (SELECT count(*) FROM future_scheduled)
  INTO v_queue_health, v_total_queue
  FROM group_counts gc
  LEFT JOIN public.account_groups g
    ON gc.bucket <> 'unassigned' AND g.id::text = gc.bucket AND g.user_id = v_user;

  -- ── 4. Gaps: active accounts with no scheduled post in next N hours ─────
  WITH active_accounts AS (
    SELECT id, 'threads'::text AS platform FROM public.accounts
      WHERE user_id = v_user AND is_active = true AND is_retired = false
    UNION ALL
    SELECT id::text, 'instagram'::text FROM public.instagram_accounts
      WHERE user_id = v_user AND is_active = true
  ),
  scheduled_soon AS (
    SELECT DISTINCT
      CASE WHEN platform = 'threads' THEN account_id
           WHEN platform = 'instagram' THEN instagram_account_id::text
      END AS account_id,
      platform
    FROM public.posts
    WHERE user_id = v_user AND status = 'scheduled'
      AND scheduled_for >= v_now AND scheduled_for < v_gap_end
  )
  SELECT count(*) INTO v_gaps_count
  FROM active_accounts aa
  LEFT JOIN scheduled_soon ss
    ON ss.account_id = aa.id AND ss.platform = aa.platform
  WHERE ss.account_id IS NULL;

  RETURN jsonb_build_object(
    'posts', v_posts,
    'groups', v_groups,
    'queueHealthByGroup', v_queue_health,
    'gapsCount', greatest(0, v_gaps_count),
    'totalQueue', v_total_queue
  );
END;
$$;

GRANT EXECUTE ON FUNCTION public.get_calendar_week(timestamptz, int, int) TO authenticated;

-- juno33 Dashboard RPCs — collapses client-side N+1 fans into single round-trips.
--
-- Four functions replace the queryFn bodies of:
--   useSystemStatus (6 queries → 1)
--   useFleetHealth (3 queries + JS classify → 1)
--   useNextUpPosts (5 queries + JS join → 1, client still formats time locale-side)
--   useActivityEvents (5 queries + JS bucketing → 1)
--
-- All SECURITY INVOKER (RLS still enforced). search_path pinned so a
-- mutable public schema can't shadow pg_catalog functions. STABLE so the
-- planner can cache within a statement.

-- ============================================================================
-- 1. get_system_status()
-- ============================================================================

CREATE OR REPLACE FUNCTION public.get_system_status()
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY INVOKER
SET search_path = public, pg_catalog
AS $$
DECLARE
  v_user text := (SELECT auth.uid()::text);
  v_now timestamptz := now();
  v_24h_ago timestamptz := v_now - interval '24 hours';
  v_30d_ahead timestamptz := v_now + interval '30 days';
  v_active_threads int;
  v_active_ig int;
  v_scheduled int;
  v_published int;
  v_failed int;
  v_pending_count int;
  v_oldest_pending timestamptz;
  v_queue_depth numeric;
  v_success_pct numeric;
BEGIN
  IF v_user IS NULL THEN
    RETURN jsonb_build_object(
      'queueDepthDays', NULL,
      'publishSuccessPct', NULL,
      'pendingApprovals', 0,
      'oldestApprovalHours', NULL
    );
  END IF;

  SELECT count(*) INTO v_active_threads
    FROM public.accounts
    WHERE user_id = v_user AND is_active = true AND is_retired = false;

  SELECT count(*) INTO v_active_ig
    FROM public.instagram_accounts
    WHERE user_id = v_user AND is_active = true;

  SELECT count(*) INTO v_scheduled FROM public.posts
    WHERE user_id = v_user AND status = 'scheduled'
      AND scheduled_for >= v_now AND scheduled_for < v_30d_ahead;

  SELECT count(*) INTO v_published FROM public.posts
    WHERE user_id = v_user AND status = 'published' AND published_at >= v_24h_ago;

  SELECT count(*) INTO v_failed FROM public.posts
    WHERE user_id = v_user AND status IN ('failed', 'publish_failed')
      AND updated_at >= v_24h_ago;

  SELECT count(*), min(created_at) INTO v_pending_count, v_oldest_pending
    FROM public.posts
    WHERE user_id = v_user AND approval_status = 'pending';

  IF (v_active_threads + v_active_ig) = 0 THEN
    v_queue_depth := NULL;
  ELSE
    v_queue_depth := round((v_scheduled::numeric / (v_active_threads + v_active_ig)::numeric) * 10) / 10;
  END IF;

  IF (v_published + v_failed) = 0 THEN
    v_success_pct := NULL;
  ELSE
    v_success_pct := round((v_published::numeric / (v_published + v_failed)::numeric) * 1000) / 10;
  END IF;

  RETURN jsonb_build_object(
    'queueDepthDays', v_queue_depth,
    'publishSuccessPct', v_success_pct,
    'pendingApprovals', v_pending_count,
    'oldestApprovalHours',
      CASE WHEN v_oldest_pending IS NULL THEN NULL
           ELSE floor(extract(epoch FROM (v_now - v_oldest_pending)) / 3600)::int
      END
  );
END;
$$;

GRANT EXECUTE ON FUNCTION public.get_system_status() TO authenticated;

-- ============================================================================
-- 2. get_fleet_health()
-- ============================================================================

CREATE OR REPLACE FUNCTION public.get_fleet_health()
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY INVOKER
SET search_path = public, pg_catalog
AS $$
DECLARE
  v_user text := (SELECT auth.uid()::text);
  v_now timestamptz := now();
  v_dormant_cutoff timestamptz := v_now - interval '72 hours';
  v_healthy int := 0;
  v_warn int := 0;
  v_crit int := 0;
  v_total int := 0;
  v_unassigned int := 0;
  v_groups jsonb;
BEGIN
  IF v_user IS NULL THEN
    RETURN jsonb_build_object('healthy', 0, 'warn', 0, 'crit', 0, 'total', 0, 'groups', '[]'::jsonb);
  END IF;

  WITH accounts_union AS (
    SELECT needs_reauth, token_expires_at, last_synced_at, group_id
      FROM public.accounts
      WHERE user_id = v_user AND is_active = true AND is_retired = false
    UNION ALL
    SELECT needs_reauth, token_expires_at, last_synced_at, group_id
      FROM public.instagram_accounts
      WHERE user_id = v_user AND is_active = true
  ),
  classified AS (
    SELECT
      group_id,
      CASE
        WHEN needs_reauth = true
          OR (token_expires_at IS NOT NULL AND token_expires_at < v_now) THEN 'crit'
        WHEN last_synced_at IS NOT NULL AND last_synced_at < v_dormant_cutoff THEN 'warn'
        ELSE 'healthy'
      END AS bucket
    FROM accounts_union
  )
  SELECT
    coalesce(count(*) FILTER (WHERE bucket = 'healthy'), 0),
    coalesce(count(*) FILTER (WHERE bucket = 'warn'), 0),
    coalesce(count(*) FILTER (WHERE bucket = 'crit'), 0),
    coalesce(count(*), 0),
    coalesce(count(*) FILTER (WHERE group_id IS NULL), 0)
  INTO v_healthy, v_warn, v_crit, v_total, v_unassigned
  FROM classified;

  WITH group_counts AS (
    SELECT group_id, count(*) AS count
    FROM (
      SELECT group_id FROM public.accounts
        WHERE user_id = v_user AND is_active = true AND is_retired = false AND group_id IS NOT NULL
      UNION ALL
      SELECT group_id FROM public.instagram_accounts
        WHERE user_id = v_user AND is_active = true AND group_id IS NOT NULL
    ) u
    GROUP BY group_id
  ),
  named AS (
    SELECT
      g.id::text AS id,
      g.name AS name,
      coalesce(nullif(g.color, ''), '#6B6B70') AS color,
      coalesce(gc.count, 0) AS count
    FROM public.account_groups g
    LEFT JOIN group_counts gc ON gc.group_id = g.id
    WHERE g.user_id = v_user
    UNION ALL
    SELECT 'unassigned'::text, 'Unassigned'::text, '#6B6B70'::text, v_unassigned::bigint
    WHERE v_unassigned > 0
  )
  SELECT coalesce(
    jsonb_agg(
      jsonb_build_object('id', id, 'name', name, 'color', color, 'count', count)
      ORDER BY count DESC
    ),
    '[]'::jsonb
  )
  INTO v_groups
  FROM named;

  RETURN jsonb_build_object(
    'healthy', v_healthy,
    'warn', v_warn,
    'crit', v_crit,
    'total', v_total,
    'groups', v_groups
  );
END;
$$;

GRANT EXECUTE ON FUNCTION public.get_fleet_health() TO authenticated;

-- ============================================================================
-- 3. get_next_up_posts(platform, window_minutes, limit, scoped_account_id, scoped_platform)
-- ============================================================================
-- Returns jsonb: { items: [...], totalQueue: int }
-- Client-side still formats `time` (locale-dependent HH:mm) and computes `isAccent`.

CREATE OR REPLACE FUNCTION public.get_next_up_posts(
  p_platform text DEFAULT 'all',      -- 'all' | 'threads' | 'ig'
  p_window_minutes int DEFAULT 60,
  p_limit int DEFAULT 3,
  p_scoped_account_id text DEFAULT NULL,
  p_scoped_platform text DEFAULT NULL -- 'threads' | 'instagram'
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
  v_window_end timestamptz := v_now + make_interval(mins => p_window_minutes);
  v_items jsonb;
  v_total bigint;
BEGIN
  IF v_user IS NULL THEN
    RETURN jsonb_build_object('items', '[]'::jsonb, 'totalQueue', 0);
  END IF;

  WITH upcoming AS (
    SELECT
      p.id,
      p.content,
      p.scheduled_for,
      p.platform,
      p.account_id,
      p.instagram_account_id
    FROM public.posts p
    WHERE p.user_id = v_user
      AND p.status = 'scheduled'
      AND p.scheduled_for >= v_now
      AND p.scheduled_for < v_window_end
      AND (p_platform = 'all'
           OR (p_platform = 'threads' AND p.platform = 'threads')
           OR (p_platform = 'ig' AND p.platform = 'instagram'))
      AND (p_scoped_account_id IS NULL
           OR (p_scoped_platform = 'threads' AND p.account_id = p_scoped_account_id)
           OR (p_scoped_platform = 'instagram' AND p.instagram_account_id::text = p_scoped_account_id))
    ORDER BY p.scheduled_for ASC
    LIMIT p_limit
  ),
  joined AS (
    SELECT
      u.id,
      u.content,
      u.scheduled_for,
      u.platform,
      coalesce(ta.username, ia.username) AS username,
      coalesce(ta.group_id, ia.group_id) AS group_id
    FROM upcoming u
    LEFT JOIN public.accounts ta
      ON ta.id = u.account_id AND ta.user_id = v_user AND u.platform = 'threads'
    LEFT JOIN public.instagram_accounts ia
      ON ia.id = u.instagram_account_id AND ia.user_id = v_user AND u.platform = 'instagram'
  )
  SELECT coalesce(
    jsonb_agg(
      jsonb_build_object(
        'id', j.id,
        'content', j.content,
        'scheduled_for', j.scheduled_for,
        'platform', j.platform,
        'username', j.username,
        'group_name', g.name,
        'group_color', coalesce(nullif(g.color, ''), '#6B6B70')
      ) ORDER BY j.scheduled_for ASC
    ),
    '[]'::jsonb
  )
  INTO v_items
  FROM joined j
  LEFT JOIN public.account_groups g ON g.id = j.group_id AND g.user_id = v_user;

  SELECT count(*) INTO v_total
  FROM public.posts p
  WHERE p.user_id = v_user
    AND p.status = 'scheduled'
    AND (p_platform = 'all'
         OR (p_platform = 'threads' AND p.platform = 'threads')
         OR (p_platform = 'ig' AND p.platform = 'instagram'))
    AND (p_scoped_account_id IS NULL
         OR (p_scoped_platform = 'threads' AND p.account_id = p_scoped_account_id)
         OR (p_scoped_platform = 'instagram' AND p.instagram_account_id::text = p_scoped_account_id));

  RETURN jsonb_build_object('items', v_items, 'totalQueue', v_total);
END;
$$;

GRANT EXECUTE ON FUNCTION public.get_next_up_posts(text, int, int, text, text) TO authenticated;

-- ============================================================================
-- 4. get_activity_events(p_limit int)
-- ============================================================================
-- Returns jsonb array of events. Client still formats `ago` (relative time
-- depends on the client clock) and derives final `title`/`detail` strings.

CREATE OR REPLACE FUNCTION public.get_activity_events(
  p_bucket_limit int DEFAULT 40
)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY INVOKER
SET search_path = public, pg_catalog
AS $$
DECLARE
  v_user text := (SELECT auth.uid()::text);
  v_result jsonb;
BEGIN
  IF v_user IS NULL THEN
    RETURN '[]'::jsonb;
  END IF;

  WITH reauth_events AS (
    SELECT
      'reauth-' || a.id AS event_id,
      'error'::text AS kind,
      a.username,
      a.group_id,
      'threads'::text AS platform,
      a.updated_at AS sort_at
    FROM public.accounts a
    WHERE a.user_id = v_user
      AND a.is_active = true AND a.is_retired = false
      AND a.needs_reauth = true
    UNION ALL
    SELECT
      'reauth-' || a.id,
      'error',
      a.username,
      a.group_id,
      'instagram',
      a.updated_at
    FROM public.instagram_accounts a
    WHERE a.user_id = v_user AND a.is_active = true AND a.needs_reauth = true
  ),
  failed_posts AS (
    SELECT
      'fail-' || p.id AS event_id,
      'error'::text AS kind,
      p.content,
      p.error_message,
      p.platform,
      p.account_id,
      p.instagram_account_id,
      p.updated_at AS sort_at
    FROM public.posts p
    WHERE p.user_id = v_user
      AND p.status IN ('failed', 'publish_failed')
    ORDER BY p.updated_at DESC
    LIMIT p_bucket_limit
  ),
  published_posts AS (
    SELECT
      'pub-' || p.id AS event_id,
      'publish'::text AS kind,
      p.content,
      p.platform,
      p.account_id,
      p.instagram_account_id,
      p.published_at AS sort_at
    FROM public.posts p
    WHERE p.user_id = v_user AND p.status = 'published' AND p.published_at IS NOT NULL
    ORDER BY p.published_at DESC
    LIMIT p_bucket_limit
  ),
  all_events AS (
    SELECT
      event_id,
      kind,
      NULL::text AS content,
      NULL::text AS error_message,
      username,
      group_id,
      platform,
      sort_at,
      'reauth'::text AS source
    FROM reauth_events
    UNION ALL
    SELECT
      fp.event_id,
      fp.kind,
      fp.content,
      fp.error_message,
      coalesce(ta.username, ia.username),
      coalesce(ta.group_id, ia.group_id),
      fp.platform,
      fp.sort_at,
      'fail'::text
    FROM failed_posts fp
    LEFT JOIN public.accounts ta
      ON ta.id = fp.account_id AND ta.user_id = v_user AND fp.platform = 'threads'
    LEFT JOIN public.instagram_accounts ia
      ON ia.id = fp.instagram_account_id AND ia.user_id = v_user AND fp.platform = 'instagram'
    UNION ALL
    SELECT
      pp.event_id,
      pp.kind,
      pp.content,
      NULL::text,
      coalesce(ta.username, ia.username),
      coalesce(ta.group_id, ia.group_id),
      pp.platform,
      pp.sort_at,
      'pub'::text
    FROM published_posts pp
    LEFT JOIN public.accounts ta
      ON ta.id = pp.account_id AND ta.user_id = v_user AND pp.platform = 'threads'
    LEFT JOIN public.instagram_accounts ia
      ON ia.id = pp.instagram_account_id AND ia.user_id = v_user AND pp.platform = 'instagram'
  )
  SELECT coalesce(
    jsonb_agg(
      jsonb_build_object(
        'event_id', ae.event_id,
        'kind', ae.kind,
        'source', ae.source,
        'username', ae.username,
        'group_name', g.name,
        'group_color', coalesce(nullif(g.color, ''), '#6B6B70'),
        'platform', ae.platform,
        'content', ae.content,
        'error_message', ae.error_message,
        'sort_at', ae.sort_at
      ) ORDER BY ae.sort_at DESC NULLS LAST
    ),
    '[]'::jsonb
  )
  INTO v_result
  FROM all_events ae
  LEFT JOIN public.account_groups g
    ON g.id = ae.group_id AND g.user_id = v_user;

  RETURN v_result;
END;
$$;

GRANT EXECUTE ON FUNCTION public.get_activity_events(int) TO authenticated;

-- Add group/account-list filtering to Dashboard next-up RPC.
-- The frontend passes p_account_ids when the global account scope is a group.
-- Without this 6-argument signature, PostgREST cannot resolve the RPC call.

DROP FUNCTION IF EXISTS public.get_next_up_posts(text, int, int, text, text, text[]);
DROP FUNCTION IF EXISTS public.get_next_up_posts(text, int, int, text, text);
DROP FUNCTION IF EXISTS public.get_next_up_posts(text, int, int, uuid, text);

CREATE OR REPLACE FUNCTION public.get_next_up_posts(
  p_platform text DEFAULT 'all',      -- 'all' | 'threads' | 'ig'
  p_window_minutes int DEFAULT 60,
  p_limit int DEFAULT 3,
  p_scoped_account_id text DEFAULT NULL,
  p_scoped_platform text DEFAULT NULL, -- 'threads' | 'instagram'
  p_account_ids text[] DEFAULT NULL
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
      AND (p_account_ids IS NULL
           OR cardinality(p_account_ids) = 0
           OR (p.platform = 'threads' AND p.account_id = ANY(p_account_ids))
           OR (p.platform = 'instagram' AND p.instagram_account_id::text = ANY(p_account_ids)))
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
         OR (p_scoped_platform = 'instagram' AND p.instagram_account_id::text = p_scoped_account_id))
    AND (p_account_ids IS NULL
         OR cardinality(p_account_ids) = 0
         OR (p.platform = 'threads' AND p.account_id = ANY(p_account_ids))
         OR (p.platform = 'instagram' AND p.instagram_account_id::text = ANY(p_account_ids)));

  RETURN jsonb_build_object('items', v_items, 'totalQueue', v_total);
END;
$$;

GRANT EXECUTE ON FUNCTION public.get_next_up_posts(text, int, int, text, text, text[]) TO authenticated;

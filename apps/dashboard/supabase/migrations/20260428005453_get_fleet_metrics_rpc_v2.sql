-- Pre-aggregates posts data for the dashboard's useFleetMetrics hook.
-- Replaces two 5000-row client queries with one server-side aggregation,
-- collapsing ~10k raw post rows down to ~hundreds of (account, day, platform)
-- buckets. SECURITY INVOKER respects RLS — function runs as the calling user.
--
-- Returns a JSONB blob with two arrays:
--   published[]: per (account_key, platform, bucket_date) — both raw totals
--                AND eqs-qualifying sums (reach >= MIN_REACH_FOR_EQS=50, mirroring
--                src/lib/eqs.ts:eqsForSignals). The two sets are needed because
--                the client uses raw totals for totalReach/sendsPlusSaves and
--                qualifying sums for the EQS formula.
--   failed[]:    per (account_key, platform, bucket_date) — count only.
--                Used for scheduleCompliance (published / (published + failed)).

ALTER TABLE public.posts
  ADD COLUMN IF NOT EXISTS views_count INTEGER,
  ADD COLUMN IF NOT EXISTS likes_count INTEGER,
  ADD COLUMN IF NOT EXISTS replies_count INTEGER,
  ADD COLUMN IF NOT EXISTS reposts_count INTEGER,
  ADD COLUMN IF NOT EXISTS quotes_count INTEGER,
  ADD COLUMN IF NOT EXISTS shares_count INTEGER;

DO $$
DECLARE
  metric text;
BEGIN
  FOREACH metric IN ARRAY ARRAY['views', 'likes', 'replies', 'reposts', 'quotes', 'shares']
  LOOP
    IF EXISTS (
      SELECT 1
      FROM information_schema.columns
      WHERE table_schema = 'public'
        AND table_name = 'posts'
        AND column_name = metric
    ) THEN
      EXECUTE format(
        'UPDATE public.posts SET %1$I_count = COALESCE(%1$I_count, %1$I, 0) WHERE %1$I_count IS NULL',
        metric
      );
    ELSE
      EXECUTE format(
        'UPDATE public.posts SET %1$I_count = COALESCE(%1$I_count, 0) WHERE %1$I_count IS NULL',
        metric
      );
    END IF;
  END LOOP;
END $$;

ALTER TABLE public.posts
  ALTER COLUMN views_count SET DEFAULT 0,
  ALTER COLUMN likes_count SET DEFAULT 0,
  ALTER COLUMN replies_count SET DEFAULT 0,
  ALTER COLUMN reposts_count SET DEFAULT 0,
  ALTER COLUMN quotes_count SET DEFAULT 0,
  ALTER COLUMN shares_count SET DEFAULT 0;

CREATE OR REPLACE FUNCTION get_fleet_metrics(
  p_user_id text,
  p_window_start timestamptz,
  p_window_end timestamptz
) RETURNS jsonb
LANGUAGE sql
STABLE
SECURITY INVOKER
SET search_path = public
AS $$
  WITH base AS (
    SELECT
      COALESCE(account_id, instagram_account_id::text) AS account_key,
      platform,
      (published_at AT TIME ZONE 'UTC')::date AS bucket_date,
      CASE WHEN platform = 'instagram'
        THEN COALESCE(ig_shares, 0)
        ELSE COALESCE(shares_count, 0)
      END AS sends,
      CASE WHEN platform = 'instagram'
        THEN COALESCE(ig_saved, 0)
        ELSE 0
      END AS saves,
      CASE WHEN platform = 'instagram'
        THEN COALESCE(ig_comment_count, 0)
        ELSE COALESCE(replies_count, 0)
      END AS comments,
      COALESCE(likes_count, 0) AS likes,
      CASE WHEN platform = 'instagram'
        THEN COALESCE(ig_reach, views_count, 0)
        ELSE COALESCE(views_count, 0)
      END AS reach
    FROM posts
    WHERE user_id = p_user_id
      AND status = 'published'
      AND published_at >= p_window_start
      AND published_at <= p_window_end
  ),
  published_agg AS (
    SELECT
      account_key,
      platform,
      bucket_date,
      COUNT(*)::int AS total_posts,
      COALESCE(SUM(sends), 0)::bigint AS total_sends,
      COALESCE(SUM(saves), 0)::bigint AS total_saves,
      COALESCE(SUM(comments), 0)::bigint AS total_comments,
      COALESCE(SUM(likes), 0)::bigint AS total_likes,
      COALESCE(SUM(reach), 0)::bigint AS total_reach,
      COALESCE(SUM(sends) FILTER (WHERE reach >= 50), 0)::bigint AS eqs_sends,
      COALESCE(SUM(saves) FILTER (WHERE reach >= 50), 0)::bigint AS eqs_saves,
      COALESCE(SUM(comments) FILTER (WHERE reach >= 50), 0)::bigint AS eqs_comments,
      COALESCE(SUM(likes) FILTER (WHERE reach >= 50), 0)::bigint AS eqs_likes,
      COALESCE(SUM(reach) FILTER (WHERE reach >= 50), 0)::bigint AS eqs_reach
    FROM base
    GROUP BY account_key, platform, bucket_date
  ),
  failed_agg AS (
    SELECT
      COALESCE(account_id, instagram_account_id::text) AS account_key,
      platform,
      (updated_at AT TIME ZONE 'UTC')::date AS bucket_date,
      COUNT(*)::int AS failed_count
    FROM posts
    WHERE user_id = p_user_id
      AND status IN ('failed', 'publish_failed')
      AND updated_at >= p_window_start
      AND updated_at <= p_window_end
    GROUP BY 1, 2, 3
  )
  SELECT jsonb_build_object(
    'published', COALESCE((SELECT jsonb_agg(to_jsonb(p)) FROM published_agg p), '[]'::jsonb),
    'failed',    COALESCE((SELECT jsonb_agg(to_jsonb(f)) FROM failed_agg f), '[]'::jsonb)
  );
$$;

GRANT EXECUTE ON FUNCTION get_fleet_metrics(text, timestamptz, timestamptz) TO authenticated, service_role;

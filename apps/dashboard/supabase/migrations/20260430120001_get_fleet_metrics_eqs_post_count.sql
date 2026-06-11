-- Surface the per-bucket count of posts that contributed to EQS so the
-- dashboard can tell a "thin sample, perfect score" from a real one.
--
-- Background: eqsForSignals (src/lib/eqs.ts) caps EQS at 100. With small
-- samples a single likes-heavy post above the reach floor (>=50) trivially
-- pushes weighted/reach above 0.05 — the scaler hits the cap and the score
-- pegs at 100/100 even though the fleet is dropping reach and shipping
-- zero quality actions. The math is correct; what's missing is a sample-
-- size signal so consumers can suppress or annotate the score.
--
-- v6 adds eqs_post_count per bucket (count of posts where reach >= 50,
-- mirroring MIN_REACH_FOR_EQS). Other bucket fields are unchanged so
-- existing client code keeps working — the new field is optional in the
-- consuming type.

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
      COALESCE(SUM(reach) FILTER (WHERE reach >= 50), 0)::bigint AS eqs_reach,
      COALESCE(COUNT(*) FILTER (WHERE reach >= 50), 0)::int AS eqs_post_count
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

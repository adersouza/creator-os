-- Fix mutable search_path on 5 SECURITY DEFINER functions
-- Supabase linter: function_search_path_mutable (0011)
-- Without SET search_path, a caller could prepend a malicious schema.

-- 1. increment_referral_uses
CREATE OR REPLACE FUNCTION public.increment_referral_uses(p_code text)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path = public
AS $function$
BEGIN
  UPDATE referral_codes
  SET uses = uses + 1, updated_at = now()
  WHERE code = p_code;
END;
$function$;

-- 2. increment_ai_generations
CREATE OR REPLACE FUNCTION public.increment_ai_generations(
  p_workspace_id text,
  p_count integer,
  p_today date,
  p_reset boolean DEFAULT false
)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path = public
AS $function$
BEGIN
  UPDATE auto_post_config
  SET
    ai_generations_today = CASE
      WHEN p_reset THEN p_count
      ELSE ai_generations_today + p_count
    END,
    ai_last_generation_date = p_today
  WHERE workspace_id = p_workspace_id;
END;
$function$;

-- 3. smart_link_analytics
CREATE OR REPLACE FUNCTION public.smart_link_analytics(
  p_link_id uuid,
  p_since timestamp with time zone
)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path = public
AS $function$
DECLARE
  v_result JSONB;
BEGIN
  SELECT jsonb_build_object(
    'clicks_by_day', COALESCE((
      SELECT jsonb_agg(row_to_json(t) ORDER BY t.day)
      FROM (
        SELECT (clicked_at AT TIME ZONE 'UTC')::date::text AS day, COUNT(*)::int AS count
        FROM smart_link_clicks
        WHERE smart_link_id = p_link_id AND clicked_at >= p_since
        GROUP BY 1
        ORDER BY 1
      ) t
    ), '[]'::jsonb),
    'by_platform', COALESCE((
      SELECT jsonb_agg(row_to_json(t))
      FROM (
        SELECT COALESCE(source_platform, 'unknown') AS name, COUNT(*)::int AS count
        FROM smart_link_clicks
        WHERE smart_link_id = p_link_id AND clicked_at >= p_since
        GROUP BY 1
        ORDER BY count DESC
      ) t
    ), '[]'::jsonb),
    'by_device', COALESCE((
      SELECT jsonb_agg(row_to_json(t))
      FROM (
        SELECT COALESCE(device_type, 'unknown') AS name, COUNT(*)::int AS count
        FROM smart_link_clicks
        WHERE smart_link_id = p_link_id AND clicked_at >= p_since
        GROUP BY 1
        ORDER BY count DESC
      ) t
    ), '[]'::jsonb),
    'by_country', COALESCE((
      SELECT jsonb_agg(row_to_json(t))
      FROM (
        SELECT COALESCE(country, 'Unknown') AS name, COUNT(*)::int AS count
        FROM smart_link_clicks
        WHERE smart_link_id = p_link_id AND clicked_at >= p_since
        GROUP BY 1
        ORDER BY count DESC
        LIMIT 10
      ) t
    ), '[]'::jsonb),
    'unique_visitors', (
      SELECT COUNT(DISTINCT fingerprint)::int
      FROM smart_link_clicks
      WHERE smart_link_id = p_link_id AND clicked_at >= p_since
        AND fingerprint IS NOT NULL
    ),
    'total_clicks', (
      SELECT COUNT(*)::int
      FROM smart_link_clicks
      WHERE smart_link_id = p_link_id AND clicked_at >= p_since
    ),
    'deep_link_attempts', (
      SELECT COUNT(*)::int
      FROM smart_link_clicks
      WHERE smart_link_id = p_link_id AND clicked_at >= p_since
        AND deep_link_attempted = true
    ),
    'conversions', COALESCE((
      SELECT jsonb_build_object(
        'count', COUNT(*)::int,
        'total_value', COALESCE(SUM(conversion_value), 0)
      )
      FROM smart_link_conversions
      WHERE smart_link_id = p_link_id AND converted_at >= p_since
    ), '{"count": 0, "total_value": 0}'::jsonb)
  ) INTO v_result;

  RETURN v_result;
END;
$function$;

-- 4. update_post_metrics_if_newer
CREATE OR REPLACE FUNCTION public.update_post_metrics_if_newer(
  p_threads_post_id text DEFAULT NULL::text,
  p_post_id text DEFAULT NULL::text,
  p_views_count bigint DEFAULT 0,
  p_likes_count bigint DEFAULT 0,
  p_replies_count bigint DEFAULT 0,
  p_reposts_count bigint DEFAULT 0,
  p_quotes_count bigint DEFAULT 0,
  p_shares_count bigint DEFAULT 0,
  p_engagement_rate double precision DEFAULT 0,
  p_total_engagement bigint DEFAULT 0
)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path = public
AS $function$
BEGIN
  UPDATE posts
  SET
    views_count = p_views_count,
    likes_count = p_likes_count,
    replies_count = p_replies_count,
    reposts_count = p_reposts_count,
    quotes_count = p_quotes_count,
    shares_count = p_shares_count,
    engagement_rate = p_engagement_rate,
    updated_at = NOW()
  WHERE
    ((p_post_id IS NOT NULL AND id = p_post_id)
    OR (p_threads_post_id IS NOT NULL AND threads_post_id = p_threads_post_id))
  AND (
    COALESCE(views_count, 0) + COALESCE(likes_count, 0)
      + COALESCE(replies_count, 0) + COALESCE(reposts_count, 0)
    <= p_total_engagement
  );
END;
$function$;

-- 5. update_ig_post_metrics_if_newer
CREATE OR REPLACE FUNCTION public.update_ig_post_metrics_if_newer(
  p_post_id text,
  p_ig_impressions bigint DEFAULT 0,
  p_ig_reach bigint DEFAULT 0,
  p_ig_saved bigint DEFAULT 0,
  p_ig_shares bigint DEFAULT 0,
  p_likes_count bigint DEFAULT 0,
  p_replies_count bigint DEFAULT 0,
  p_ig_plays bigint DEFAULT 0,
  p_ig_video_views bigint DEFAULT 0,
  p_engagement_rate double precision DEFAULT 0,
  p_total_engagement bigint DEFAULT 0,
  p_ig_reels_avg_watch_time double precision DEFAULT 0,
  p_ig_crossposted_views bigint DEFAULT 0,
  p_ig_facebook_views bigint DEFAULT 0,
  p_ig_reels_video_view_total_time bigint DEFAULT 0,
  p_ig_clips_replays_count integer DEFAULT 0,
  p_ig_reels_aggregated_all_plays_count bigint DEFAULT 0
)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path = public
AS $function$
BEGIN
  UPDATE posts SET
    ig_impressions = p_ig_impressions,
    ig_reach = p_ig_reach,
    ig_saved = p_ig_saved,
    ig_shares = p_ig_shares,
    likes_count = p_likes_count,
    replies_count = p_replies_count,
    ig_plays = p_ig_plays,
    ig_video_views = p_ig_video_views,
    engagement_rate = p_engagement_rate,
    ig_reels_avg_watch_time = p_ig_reels_avg_watch_time,
    ig_crossposted_views = p_ig_crossposted_views,
    ig_facebook_views = p_ig_facebook_views,
    ig_reels_video_view_total_time = p_ig_reels_video_view_total_time,
    ig_clips_replays_count = p_ig_clips_replays_count,
    ig_reels_aggregated_all_plays_count = p_ig_reels_aggregated_all_plays_count,
    updated_at = NOW()
  WHERE id = p_post_id
  AND (
    COALESCE(ig_impressions, 0) + COALESCE(likes_count, 0)
    + COALESCE(replies_count, 0) + COALESCE(ig_saved, 0)
    <= p_total_engagement
  );
END;
$function$;

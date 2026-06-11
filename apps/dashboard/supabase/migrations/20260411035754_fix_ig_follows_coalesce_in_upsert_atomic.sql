-- Reconstructed from schema_migrations on prod (remote-only).
-- version: 20260411035754
-- applied-by: fix_ig_follows_coalesce_in_upsert_atomic migration row


CREATE OR REPLACE FUNCTION public.upsert_account_analytics_atomic(p_analytics jsonb, p_metrics_history jsonb)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
AS $function$
BEGIN
  INSERT INTO account_analytics (
    account_id, date,
    followers_count, following_count, follower_growth,
    total_views, total_likes, total_replies, total_reposts,
    total_quotes, total_shares, total_clicks, total_saves,
    total_reach, engagement_rate, posts_count,
    ig_reach, ig_impressions, ig_accounts_engaged,
    ig_total_interactions, ig_profile_views, ig_website_clicks,
    ig_non_follower_reach_pct, ig_new_follows, ig_unfollows,
    ig_content_type_breakdown, ig_online_followers, ig_tagged_media_count
  )
  VALUES (
    p_analytics->>'account_id',
    (p_analytics->>'date')::date,
    COALESCE((p_analytics->>'followers_count')::bigint, 0),
    COALESCE((p_analytics->>'following_count')::bigint, 0),
    COALESCE((p_analytics->>'follower_growth')::integer, 0),
    COALESCE((p_analytics->>'total_views')::bigint, 0),
    COALESCE((p_analytics->>'total_likes')::bigint, 0),
    COALESCE((p_analytics->>'total_replies')::bigint, 0),
    COALESCE((p_analytics->>'total_reposts')::bigint, 0),
    COALESCE((p_analytics->>'total_quotes')::bigint, 0),
    COALESCE((p_analytics->>'total_shares')::bigint, 0),
    COALESCE((p_analytics->>'total_clicks')::bigint, 0),
    COALESCE((p_analytics->>'total_saves')::bigint, 0),
    COALESCE((p_analytics->>'total_reach')::bigint, 0),
    COALESCE((p_analytics->>'engagement_rate')::numeric, 0),
    COALESCE((p_analytics->>'posts_count')::int, 0),
    COALESCE((p_analytics->>'ig_reach')::integer, 0),
    COALESCE((p_analytics->>'ig_impressions')::integer, 0),
    COALESCE((p_analytics->>'ig_accounts_engaged')::integer, 0),
    COALESCE((p_analytics->>'ig_total_interactions')::integer, 0),
    COALESCE((p_analytics->>'ig_profile_views')::integer, 0),
    COALESCE((p_analytics->>'ig_website_clicks')::integer, 0),
    COALESCE((p_analytics->>'ig_non_follower_reach_pct')::numeric, 0),
    -- NULL sentinel: if key absent from JSON, store NULL so COALESCE on conflict
    -- can preserve the previous day's value instead of overwriting with 0.
    (p_analytics->>'ig_new_follows')::integer,
    (p_analytics->>'ig_unfollows')::integer,
    (p_analytics->'ig_content_type_breakdown')::jsonb,
    (p_analytics->'ig_online_followers')::jsonb,
    COALESCE((p_analytics->>'ig_tagged_media_count')::integer, 0)
  )
  ON CONFLICT (account_id, date) DO UPDATE SET
    followers_count = COALESCE(EXCLUDED.followers_count, account_analytics.followers_count),
    following_count = COALESCE(EXCLUDED.following_count, account_analytics.following_count),
    follower_growth = COALESCE(EXCLUDED.follower_growth, account_analytics.follower_growth),
    total_views = EXCLUDED.total_views,
    total_likes = EXCLUDED.total_likes,
    total_replies = EXCLUDED.total_replies,
    total_reposts = EXCLUDED.total_reposts,
    total_quotes = EXCLUDED.total_quotes,
    total_shares = EXCLUDED.total_shares,
    total_clicks = EXCLUDED.total_clicks,
    total_saves = EXCLUDED.total_saves,
    total_reach = EXCLUDED.total_reach,
    engagement_rate = EXCLUDED.engagement_rate,
    posts_count = EXCLUDED.posts_count,
    ig_reach = EXCLUDED.ig_reach,
    ig_impressions = EXCLUDED.ig_impressions,
    ig_accounts_engaged = EXCLUDED.ig_accounts_engaged,
    ig_total_interactions = EXCLUDED.ig_total_interactions,
    ig_profile_views = EXCLUDED.ig_profile_views,
    ig_website_clicks = EXCLUDED.ig_website_clicks,
    ig_non_follower_reach_pct = EXCLUDED.ig_non_follower_reach_pct,
    -- Preserve existing value when this sync cycle didn't return these metrics
    ig_new_follows = COALESCE(EXCLUDED.ig_new_follows, account_analytics.ig_new_follows),
    ig_unfollows = COALESCE(EXCLUDED.ig_unfollows, account_analytics.ig_unfollows),
    ig_content_type_breakdown = COALESCE(EXCLUDED.ig_content_type_breakdown, account_analytics.ig_content_type_breakdown),
    ig_online_followers = COALESCE(EXCLUDED.ig_online_followers, account_analytics.ig_online_followers),
    ig_tagged_media_count = EXCLUDED.ig_tagged_media_count;

  IF p_metrics_history IS NOT NULL THEN
    INSERT INTO account_metrics_history (
      account_id, platform, date,
      followers_count, total_views, total_likes, total_replies,
      total_reposts, total_shares, engagement_rate, posts_count
    )
    VALUES (
      p_metrics_history->>'account_id',
      COALESCE(p_metrics_history->>'platform', 'threads'),
      (p_metrics_history->>'date')::date,
      COALESCE((p_metrics_history->>'followers_count')::bigint, 0),
      COALESCE((p_metrics_history->>'total_views')::bigint, 0),
      COALESCE((p_metrics_history->>'total_likes')::bigint, 0),
      COALESCE((p_metrics_history->>'total_replies')::bigint, 0),
      COALESCE((p_metrics_history->>'total_reposts')::bigint, 0),
      COALESCE((p_metrics_history->>'total_shares')::bigint, 0),
      COALESCE((p_metrics_history->>'engagement_rate')::numeric, 0),
      COALESCE((p_metrics_history->>'posts_count')::int, 0)
    )
    ON CONFLICT (account_id, date) DO UPDATE SET
      followers_count = EXCLUDED.followers_count,
      total_views = EXCLUDED.total_views,
      total_likes = EXCLUDED.total_likes,
      total_replies = EXCLUDED.total_replies,
      total_reposts = EXCLUDED.total_reposts,
      total_shares = EXCLUDED.total_shares,
      engagement_rate = EXCLUDED.engagement_rate,
      posts_count = EXCLUDED.posts_count;
  END IF;

  RETURN jsonb_build_object('success', true);
END;
$function$;

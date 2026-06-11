-- v6: stop COALESCE-to-zero on Meta breakdown fields that may be absent.
--
-- v5 wrote `0` to ig_non_follower_reach_pct / ig_follower_reach /
-- ig_non_follower_reach when the JSON payload didn't carry them, and
-- the ON CONFLICT branch overwrote any previously-stored value with the
-- same `0` on every subsequent sync. That corrupts the signal — a real
-- "0% non-follower reach" measurement is indistinguishable from "Meta
-- breakdown call failed for this account this run".
--
-- v6 changes:
--   1. INSERT: write the field as-is (NULL when JSON key absent) instead
--      of COALESCE-to-zero. Columns are nullable in the schema; the
--      original DEFAULT 0 only applied to legacy rows.
--   2. UPDATE: use COALESCE(EXCLUDED.x, account_analytics.x) so a missing
--      payload preserves the prior value rather than clobbering it.
--
-- All other fields keep their v5 behavior so non-breakdown call sites are
-- untouched. Function signature unchanged — existing callers transparent.

CREATE OR REPLACE FUNCTION upsert_account_analytics_atomic(
  p_analytics JSONB,
  p_metrics_history JSONB
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
  INSERT INTO account_analytics (
    account_id, date,
    followers_count, following_count, follower_growth,
    total_views, total_likes, total_replies, total_reposts,
    total_quotes, total_shares, total_clicks, total_saves,
    total_reach, engagement_rate, posts_count,
    ig_reach, ig_impressions, ig_accounts_engaged,
    ig_total_interactions, ig_profile_views, ig_website_clicks,
    ig_non_follower_reach_pct, ig_follower_reach, ig_non_follower_reach,
    ig_new_follows, ig_unfollows,
    ig_content_type_breakdown, ig_online_followers, ig_tagged_media_count,
    threads_views_by_source
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
    -- v6: NULL when key absent (was COALESCE→0 in v5 — corrupted "no breakdown" as real "0%")
    (p_analytics->>'ig_non_follower_reach_pct')::numeric,
    (p_analytics->>'ig_follower_reach')::integer,
    (p_analytics->>'ig_non_follower_reach')::integer,
    COALESCE((p_analytics->>'ig_new_follows')::integer, 0),
    COALESCE((p_analytics->>'ig_unfollows')::integer, 0),
    (p_analytics->'ig_content_type_breakdown')::jsonb,
    (p_analytics->'ig_online_followers')::jsonb,
    COALESCE((p_analytics->>'ig_tagged_media_count')::integer, 0),
    (p_analytics->'threads_views_by_source')::jsonb
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
    -- v6: preserve prior real value when payload lacks the breakdown
    ig_non_follower_reach_pct = COALESCE(EXCLUDED.ig_non_follower_reach_pct, account_analytics.ig_non_follower_reach_pct),
    ig_follower_reach = COALESCE(EXCLUDED.ig_follower_reach, account_analytics.ig_follower_reach),
    ig_non_follower_reach = COALESCE(EXCLUDED.ig_non_follower_reach, account_analytics.ig_non_follower_reach),
    ig_new_follows = EXCLUDED.ig_new_follows,
    ig_unfollows = EXCLUDED.ig_unfollows,
    ig_content_type_breakdown = COALESCE(EXCLUDED.ig_content_type_breakdown, account_analytics.ig_content_type_breakdown),
    ig_online_followers = COALESCE(EXCLUDED.ig_online_followers, account_analytics.ig_online_followers),
    ig_tagged_media_count = EXCLUDED.ig_tagged_media_count,
    threads_views_by_source = COALESCE(EXCLUDED.threads_views_by_source, account_analytics.threads_views_by_source);

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
$$;

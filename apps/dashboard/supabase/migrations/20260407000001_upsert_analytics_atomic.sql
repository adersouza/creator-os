-- Atomic analytics upsert — wraps account_analytics + account_metrics_history
-- in a single transaction so partial failures can't leave inconsistent state.

CREATE OR REPLACE FUNCTION upsert_account_analytics_atomic(
  p_analytics JSONB,
  p_metrics_history JSONB
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
  -- Upsert account_analytics
  INSERT INTO account_analytics (
    account_id, date, user_id, platform,
    followers_count, following_count,
    total_views, total_likes, total_replies, total_reposts,
    total_quotes, total_shares, total_clicks, total_saves,
    engagement_rate, posts_count
  )
  VALUES (
    p_analytics->>'account_id',
    (p_analytics->>'date')::date,
    p_analytics->>'user_id',
    COALESCE(p_analytics->>'platform', 'threads'),
    COALESCE((p_analytics->>'followers_count')::bigint, 0),
    COALESCE((p_analytics->>'following_count')::bigint, 0),
    COALESCE((p_analytics->>'total_views')::bigint, 0),
    COALESCE((p_analytics->>'total_likes')::bigint, 0),
    COALESCE((p_analytics->>'total_replies')::bigint, 0),
    COALESCE((p_analytics->>'total_reposts')::bigint, 0),
    COALESCE((p_analytics->>'total_quotes')::bigint, 0),
    COALESCE((p_analytics->>'total_shares')::bigint, 0),
    COALESCE((p_analytics->>'total_clicks')::bigint, 0),
    COALESCE((p_analytics->>'total_saves')::bigint, 0),
    COALESCE((p_analytics->>'engagement_rate')::numeric, 0),
    COALESCE((p_analytics->>'posts_count')::int, 0)
  )
  ON CONFLICT (account_id, date) DO UPDATE SET
    followers_count = COALESCE(EXCLUDED.followers_count, account_analytics.followers_count),
    following_count = COALESCE(EXCLUDED.following_count, account_analytics.following_count),
    total_views = EXCLUDED.total_views,
    total_likes = EXCLUDED.total_likes,
    total_replies = EXCLUDED.total_replies,
    total_reposts = EXCLUDED.total_reposts,
    total_quotes = EXCLUDED.total_quotes,
    total_shares = EXCLUDED.total_shares,
    total_clicks = EXCLUDED.total_clicks,
    total_saves = EXCLUDED.total_saves,
    engagement_rate = EXCLUDED.engagement_rate,
    posts_count = EXCLUDED.posts_count,
    updated_at = now();

  -- Upsert account_metrics_history (same transaction)
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

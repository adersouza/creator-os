-- Migration: Monotonic metric update functions
-- Prevents last-write-wins data races between webhook-processor and analytics-pipeline.
-- Only overwrites metrics when the new total engagement >= existing total engagement,
-- ensuring fresher data always wins regardless of write order.

-- ============================================================================
-- Threads post metrics (used by webhook-processor + threadsRefresh)
-- ============================================================================

CREATE OR REPLACE FUNCTION update_post_metrics_if_newer(
  p_threads_post_id TEXT DEFAULT NULL,
  p_post_id TEXT DEFAULT NULL,
  p_views_count BIGINT DEFAULT 0,
  p_likes_count BIGINT DEFAULT 0,
  p_replies_count BIGINT DEFAULT 0,
  p_reposts_count BIGINT DEFAULT 0,
  p_quotes_count BIGINT DEFAULT 0,
  p_shares_count BIGINT DEFAULT 0,
  p_engagement_rate DOUBLE PRECISION DEFAULT 0,
  p_total_engagement BIGINT DEFAULT 0
) RETURNS VOID AS $$
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
    -- Only overwrite if incoming metrics are >= existing (monotonic)
    COALESCE(views_count, 0) + COALESCE(likes_count, 0)
      + COALESCE(replies_count, 0) + COALESCE(reposts_count, 0)
    <= p_total_engagement
  );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

GRANT EXECUTE ON FUNCTION update_post_metrics_if_newer(TEXT, TEXT, BIGINT, BIGINT, BIGINT, BIGINT, BIGINT, BIGINT, DOUBLE PRECISION, BIGINT) TO service_role;

-- ============================================================================
-- Instagram post metrics (used by webhook-processor)
-- ============================================================================

CREATE OR REPLACE FUNCTION update_ig_post_metrics_if_newer(
  p_post_id TEXT,
  p_ig_impressions BIGINT DEFAULT 0,
  p_ig_reach BIGINT DEFAULT 0,
  p_ig_saved BIGINT DEFAULT 0,
  p_ig_shares BIGINT DEFAULT 0,
  p_likes_count BIGINT DEFAULT 0,
  p_replies_count BIGINT DEFAULT 0,
  p_ig_plays BIGINT DEFAULT 0,
  p_ig_video_views BIGINT DEFAULT 0,
  p_engagement_rate DOUBLE PRECISION DEFAULT 0,
  p_total_engagement BIGINT DEFAULT 0
) RETURNS VOID AS $$
BEGIN
  UPDATE posts
  SET
    ig_impressions = p_ig_impressions,
    ig_reach = p_ig_reach,
    ig_saved = p_ig_saved,
    ig_shares = p_ig_shares,
    likes_count = p_likes_count,
    replies_count = p_replies_count,
    ig_plays = p_ig_plays,
    ig_video_views = p_ig_video_views,
    engagement_rate = p_engagement_rate,
    updated_at = NOW()
  WHERE id = p_post_id
  AND (
    COALESCE(ig_impressions, 0) + COALESCE(likes_count, 0)
      + COALESCE(replies_count, 0) + COALESCE(ig_saved, 0)
    <= p_total_engagement
  );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

GRANT EXECUTE ON FUNCTION update_ig_post_metrics_if_newer(TEXT, BIGINT, BIGINT, BIGINT, BIGINT, BIGINT, BIGINT, BIGINT, BIGINT, DOUBLE PRECISION, BIGINT) TO service_role;

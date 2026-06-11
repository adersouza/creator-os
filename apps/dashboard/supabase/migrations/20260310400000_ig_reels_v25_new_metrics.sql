-- Add v25.0 reel metrics: total view time, replays, aggregated plays
ALTER TABLE posts ADD COLUMN IF NOT EXISTS ig_reels_video_view_total_time BIGINT DEFAULT 0;
ALTER TABLE posts ADD COLUMN IF NOT EXISTS ig_clips_replays_count INTEGER DEFAULT 0;
ALTER TABLE posts ADD COLUMN IF NOT EXISTS ig_reels_aggregated_all_plays_count BIGINT DEFAULT 0;

-- Recreate the metric update RPC with new params
DROP FUNCTION IF EXISTS update_ig_post_metrics_if_newer(
  TEXT, BIGINT, BIGINT, BIGINT, BIGINT, BIGINT, BIGINT, BIGINT, BIGINT, DOUBLE PRECISION, BIGINT, DOUBLE PRECISION, BIGINT, BIGINT
);

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
  p_total_engagement BIGINT DEFAULT 0,
  p_ig_reels_avg_watch_time DOUBLE PRECISION DEFAULT 0,
  p_ig_crossposted_views BIGINT DEFAULT 0,
  p_ig_facebook_views BIGINT DEFAULT 0,
  p_ig_reels_video_view_total_time BIGINT DEFAULT 0,
  p_ig_clips_replays_count INTEGER DEFAULT 0,
  p_ig_reels_aggregated_all_plays_count BIGINT DEFAULT 0
) RETURNS VOID AS $$
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
$$ LANGUAGE plpgsql SECURITY DEFINER;

GRANT EXECUTE ON FUNCTION update_ig_post_metrics_if_newer TO service_role;

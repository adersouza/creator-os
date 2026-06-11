-- Add columns for follows_and_unfollows metric (Fix 4) and content type breakdown (Fix 8)
-- from Instagram API v25.0 audit

-- Daily follow/unfollow counts from follows_and_unfollows metric with follow_type breakdown
ALTER TABLE account_analytics ADD COLUMN IF NOT EXISTS ig_new_follows INTEGER DEFAULT 0;
ALTER TABLE account_analytics ADD COLUMN IF NOT EXISTS ig_unfollows INTEGER DEFAULT 0;

-- Content type performance breakdown (feed vs reels vs story) from media_product_type breakdown
-- Stored as JSONB: { "feed": { "reach": N, "views": N, ... }, "reels": { ... }, "story": { ... } }
ALTER TABLE account_analytics ADD COLUMN IF NOT EXISTS ig_content_type_breakdown JSONB;

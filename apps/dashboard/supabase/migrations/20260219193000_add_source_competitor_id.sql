-- Add missing columns to auto_post_queue for engagement tracking,
-- content type classification, and competitor source tracking.
ALTER TABLE auto_post_queue ADD COLUMN IF NOT EXISTS source_competitor_id TEXT;
ALTER TABLE auto_post_queue ADD COLUMN IF NOT EXISTS content_type TEXT;
ALTER TABLE auto_post_queue ADD COLUMN IF NOT EXISTS engagement_rate NUMERIC;
ALTER TABLE auto_post_queue ADD COLUMN IF NOT EXISTS posted_at TIMESTAMPTZ;
ALTER TABLE auto_post_queue ADD COLUMN IF NOT EXISTS threads_post_id TEXT;
ALTER TABLE auto_post_queue ADD COLUMN IF NOT EXISTS views_at_24h INTEGER;
ALTER TABLE auto_post_queue ADD COLUMN IF NOT EXISTS likes_count INTEGER;
ALTER TABLE auto_post_queue ADD COLUMN IF NOT EXISTS replies_count INTEGER;
ALTER TABLE auto_post_queue ADD COLUMN IF NOT EXISTS reposts_count INTEGER;
ALTER TABLE auto_post_queue ADD COLUMN IF NOT EXISTS engagement_fetched_at TIMESTAMPTZ;
ALTER TABLE auto_post_queue ADD COLUMN IF NOT EXISTS predicted_viral_score NUMERIC;
ALTER TABLE auto_post_queue ADD COLUMN IF NOT EXISTS source_type TEXT;
ALTER TABLE auto_post_queue ADD COLUMN IF NOT EXISTS source_content TEXT;

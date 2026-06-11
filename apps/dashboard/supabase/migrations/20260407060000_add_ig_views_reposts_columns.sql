-- Add ig_views column (Meta v21+ primary metric, replaces deprecated impressions)
-- and ig_reposts column (fetched from API but never persisted).
ALTER TABLE posts ADD COLUMN IF NOT EXISTS ig_views INTEGER DEFAULT 0;
ALTER TABLE posts ADD COLUMN IF NOT EXISTS ig_reposts INTEGER DEFAULT 0;

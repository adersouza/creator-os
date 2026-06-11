-- Add scraped_at column to competitor_top_posts for recency weighting
-- This allows the auto-poster to prefer freshly scraped content over stale data

ALTER TABLE competitor_top_posts
  ADD COLUMN IF NOT EXISTS scraped_at timestamptz DEFAULT now();

-- Add status column to competitors for tracking private/deleted accounts
ALTER TABLE competitors
  ADD COLUMN IF NOT EXISTS sync_status text DEFAULT 'active'
    CHECK (sync_status IN ('active', 'private', 'deleted', 'rate_limited', 'error'));

ALTER TABLE competitors
  ADD COLUMN IF NOT EXISTS consecutive_failures int DEFAULT 0;

-- Index for recency-weighted queries
CREATE INDEX IF NOT EXISTS idx_competitor_top_posts_scraped_at
  ON competitor_top_posts (scraped_at DESC);

-- Index for sync_status filtering
CREATE INDEX IF NOT EXISTS idx_competitors_sync_status
  ON competitors (sync_status);

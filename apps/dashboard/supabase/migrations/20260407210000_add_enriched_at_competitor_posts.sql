-- Add enriched_at column to track Apify scrape freshness
ALTER TABLE competitor_top_posts
  ADD COLUMN IF NOT EXISTS enriched_at TIMESTAMPTZ;

-- Index for finding unenriched posts efficiently
CREATE INDEX IF NOT EXISTS idx_competitor_top_posts_enriched
  ON competitor_top_posts (enriched_at NULLS FIRST)
  WHERE permalink IS NOT NULL;

-- Add retry_count to posts table for transient failure recovery
ALTER TABLE posts ADD COLUMN IF NOT EXISTS retry_count INT DEFAULT 0;

-- Index for the cron retry query
CREATE INDEX IF NOT EXISTS idx_posts_failed_retry
  ON posts (status, platform, updated_at, retry_count)
  WHERE status = 'failed' AND retry_count < 3;

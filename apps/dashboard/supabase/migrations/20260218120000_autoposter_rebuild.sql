-- Auto-poster rebuild: add content_type and source_competitor_id to queue
-- These columns support the content variety engine and smart competitor rotation

ALTER TABLE auto_post_queue
  ADD COLUMN IF NOT EXISTS content_type text,
  ADD COLUMN IF NOT EXISTS source_competitor_id uuid;

-- Index for finding due posts efficiently
CREATE INDEX IF NOT EXISTS idx_auto_post_queue_scheduled_due
  ON auto_post_queue (workspace_id, status, scheduled_for)
  WHERE status IN ('pending', 'queued');

-- Index for dedup lookups (source_content in last 7 days)
CREATE INDEX IF NOT EXISTS idx_auto_post_queue_source_content
  ON auto_post_queue (workspace_id, source_content)
  WHERE source_content IS NOT NULL;

-- Index for content type performance tracking
CREATE INDEX IF NOT EXISTS idx_auto_post_queue_content_type_perf
  ON auto_post_queue (workspace_id, content_type, status)
  WHERE content_type IS NOT NULL AND status = 'posted';

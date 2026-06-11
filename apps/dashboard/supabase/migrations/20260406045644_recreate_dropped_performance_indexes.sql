-- Reconstructed from schema_migrations on prod (remote-only).
-- version: 20260406045644
-- applied-by: recreate_dropped_performance_indexes migration row


-- =============================================================================
-- Recreate performance indexes that were dropped in batch1/batch2 (March 6)
-- and never recreated. These are actively used by webhook processor, 
-- publish worker, and sync orchestrator.
-- =============================================================================

-- Critical: webhook-processor.ts queries posts.threads_post_id on every event
CREATE INDEX IF NOT EXISTS idx_posts_threads_post_id
  ON posts(threads_post_id) WHERE threads_post_id IS NOT NULL;

-- Publish worker: pending queue items for cron pickup
CREATE INDEX IF NOT EXISTS idx_auto_post_queue_pending
  ON auto_post_queue(scheduled_for)
  WHERE status = 'pending';

-- Publish worker: retry processing
CREATE INDEX IF NOT EXISTS idx_auto_post_queue_retry_pending
  ON auto_post_queue(next_retry_at ASC)
  WHERE status IN ('failed', 'retry_pending');

-- Sync orchestrator: job status queries
CREATE INDEX IF NOT EXISTS idx_sync_jobs_status
  ON sync_jobs(status);

CREATE INDEX IF NOT EXISTS idx_sync_jobs_status_created
  ON sync_jobs(status, created_at DESC);

-- Webhook processor: pending IG webhook event pickup
CREATE INDEX IF NOT EXISTS idx_ig_webhook_pending
  ON ig_webhook_events(processed, received_at)
  WHERE processed = false;

-- Reply rate limiting: account + date range queries
CREATE INDEX IF NOT EXISTS idx_sent_replies_account_created
  ON sent_replies(account_id, created_at DESC);

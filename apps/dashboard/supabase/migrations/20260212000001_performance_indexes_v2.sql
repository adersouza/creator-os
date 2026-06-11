-- Migration: Performance Indexes V2
-- Date: 2026-02-12
-- Purpose: Add indexes for high-cardinality query patterns identified in API/cron audit
-- Impact: Improves webhook processing, post lookups, retry queries, analytics

-- ============================================================================
-- 1. Posts: threads_post_id lookup (webhook processor + reply sync)
-- Query: WHERE threads_post_id = X
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_posts_threads_post_id
  ON posts(threads_post_id)
  WHERE threads_post_id IS NOT NULL;

-- ============================================================================
-- 2. Posts: user + created_at for post listing/pagination
-- Query: WHERE user_id = X ORDER BY created_at DESC
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_posts_user_created
  ON posts(user_id, created_at DESC);

-- ============================================================================
-- 3. Auto-post queue: retry processing for failed items
-- Query: WHERE status IN ('failed','retry_pending') AND next_retry_at <= now()
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_auto_post_queue_retry
  ON auto_post_queue(next_retry_at ASC)
  WHERE status IN ('failed', 'retry_pending');

-- ============================================================================
-- 4. Auto-post queue: account-level batch processing
-- Query: WHERE account_id = X AND status = 'pending'
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_auto_post_queue_account_status
  ON auto_post_queue(account_id, status)
  WHERE status IN ('pending', 'failed', 'retry_pending');

-- ============================================================================
-- 5. Auto-post activity: workspace health checks
-- Query: WHERE workspace_id = X ORDER BY created_at DESC
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_auto_post_activity_workspace_created
  ON auto_post_activity(workspace_id, created_at DESC);

-- ============================================================================
-- 6. IG webhook events: user-scoped processing
-- Query: WHERE ig_user_id = X AND processed = false ORDER BY received_at
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_ig_webhook_events_user_pending
  ON ig_webhook_events(ig_user_id, received_at ASC)
  WHERE processed = false;

-- ============================================================================
-- 7. Threads webhook events: user + type for replay filtering
-- Query: WHERE threads_user_id = X AND event_type = Y AND processed = false
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_threads_webhook_user_type_pending
  ON threads_webhook_events(threads_user_id, event_type)
  WHERE processed = false;

-- ============================================================================
-- 8. Sync jobs: status + recency for worker polling
-- Query: WHERE status = 'pending' ORDER BY created_at ASC
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_sync_jobs_status_created
  ON sync_jobs(status, created_at ASC)
  WHERE status IN ('pending', 'processing');

-- ============================================================================
-- 9. IG rate limit tracking: (removed — account_id already has unique constraint)
-- ============================================================================

-- ============================================================================
-- 10. Sent replies: account + time for pagination
-- Query: WHERE account_id = X ORDER BY created_at DESC
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_sent_replies_account_created
  ON sent_replies(account_id, created_at DESC);

-- ============================================================================
-- 11. IG mentions: user + mentioned_at for pagination
-- Query: WHERE user_id = X ORDER BY mentioned_at DESC
-- (idx_ig_mentions_user_id already exists — skipping)
-- ============================================================================

-- ============================================================================
-- 12. IG pending containers: status + created for publisher cron
-- Query: WHERE status = 'pending' ORDER BY created_at ASC
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_ig_pending_containers_pending_created
  ON ig_pending_containers(created_at ASC)
  WHERE status = 'pending';

-- ============================================================================
-- 13. Competitor posts: competitor scoping for analytics
-- Query: WHERE competitor_id = X ORDER BY created_at DESC
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_competitor_posts_competitor_created
  ON competitor_posts(competitor_id, created_at DESC);

-- ============================================================================
-- 14. Cron runs: job + time for health dashboard queries
-- Already has idx_cron_runs_job_started, adding status filter
-- Query: WHERE job_name = X AND status = 'failed' ORDER BY started_at DESC
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_cron_runs_failed
  ON cron_runs(job_name, started_at DESC)
  WHERE status = 'failed';

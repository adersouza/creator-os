-- Composite indexes for hot query patterns
-- These cover the most common WHERE clauses in cron jobs and API routes

-- Posts: frequently queried by account_id + status
CREATE INDEX IF NOT EXISTS idx_posts_account_status
  ON posts(account_id, status);

-- Posts: queried by user_id + status (scheduled count, etc.)
CREATE INDEX IF NOT EXISTS idx_posts_user_status
  ON posts(user_id, status);

-- Posts: queried by account_id + status + published_at (analytics, tiered sync)
CREATE INDEX IF NOT EXISTS idx_posts_account_status_published
  ON posts(account_id, status, published_at DESC);

-- Sent replies: queried by account_id + created_at (rate limiting)
CREATE INDEX IF NOT EXISTS idx_sent_replies_account_created
  ON sent_replies(account_id, created_at DESC);

-- Auto post queue: queried by workspace_id + status
CREATE INDEX IF NOT EXISTS idx_auto_post_queue_workspace_status
  ON auto_post_queue(workspace_id, status);

-- Account analytics: queried by account_id + date
CREATE INDEX IF NOT EXISTS idx_account_analytics_account_date
  ON account_analytics(account_id, date DESC);

-- Webhook events: queried by processed + next_retry_at
CREATE INDEX IF NOT EXISTS idx_threads_webhook_processed
  ON threads_webhook_events(processed, next_retry_at);
CREATE INDEX IF NOT EXISTS idx_ig_webhook_processed
  ON ig_webhook_events(processed, next_retry_at);

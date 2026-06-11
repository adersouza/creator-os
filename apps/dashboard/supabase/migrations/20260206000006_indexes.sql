-- Migration: Add missing performance indexes
-- Date: 2026-02-06
-- Purpose: Optimize common query patterns across cron jobs and API routes

-- Posts: scheduled posts cron query
CREATE INDEX IF NOT EXISTS idx_posts_scheduled_pending
  ON posts(scheduled_for)
  WHERE status = 'scheduled';

-- Posts: by platform and account
CREATE INDEX IF NOT EXISTS idx_posts_platform_account
  ON posts(platform, account_id);

-- Posts: published posts sorted by date
CREATE INDEX IF NOT EXISTS idx_posts_published_date
  ON posts(published_at DESC)
  WHERE status = 'published';

-- Auto-post queue: pending items by scheduled time
CREATE INDEX IF NOT EXISTS idx_auto_post_queue_pending
  ON auto_post_queue(scheduled_for)
  WHERE status = 'pending';

-- IG webhook events: unprocessed by received time
CREATE INDEX IF NOT EXISTS idx_ig_webhook_pending
  ON ig_webhook_events(received_at)
  WHERE processed_at IS NULL;

-- Competitor posts: by competitor and fetch date
CREATE INDEX IF NOT EXISTS idx_competitor_posts_fetched
  ON competitor_posts(competitor_id, fetched_at DESC);

-- Rate limits: by account and date
ALTER TABLE rate_limit_tracking
  ADD COLUMN IF NOT EXISTS date DATE DEFAULT CURRENT_DATE;

CREATE INDEX IF NOT EXISTS idx_rate_limit_account_date
  ON rate_limit_tracking(account_id, date);

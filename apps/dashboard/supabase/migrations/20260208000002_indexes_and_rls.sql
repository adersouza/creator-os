-- Migration: Performance Indexes, RLS Policies, CHECK Constraints, Cleanup Functions
-- Date: 2026-02-08
-- Phase: Backend Redesign Phase 4 (Performance)
-- Source: Section 3 of 06-backend-master-plan.md
--
-- This migration consolidates:
--   3.1 Missing Indexes (10 indexes from the plan)
--   3.2 RLS Policy Fixes (4 tables + group_analytics fix)
--   3.3 CHECK Constraints on status fields
--   3.4 cleanup_old_cron_runs() function

-- ============================================================================
-- SECTION 1: Missing Indexes (Plan Section 3.1)
-- ============================================================================
-- Uses CREATE INDEX IF NOT EXISTS (not CONCURRENTLY — unsupported in transactions)

-- 1. Posts: Scheduled posts query (used by scheduled-posts cron every minute)
-- Supports: WHERE status = 'scheduled' AND scheduled_for <= NOW()
-- Note: idx_posts_scheduled_pending already exists from earlier migration,
--       this is a no-op IF NOT EXISTS
CREATE INDEX IF NOT EXISTS idx_posts_scheduled_pending
  ON posts(scheduled_for)
  WHERE status = 'scheduled';

-- 2. Posts: Platform + instagram_account_id (used by analytics, service layer)
-- Supports: WHERE platform = 'instagram' AND instagram_account_id = ?
-- Note: Different from existing idx_posts_platform_account which indexes (platform, account_id)
CREATE INDEX IF NOT EXISTS idx_posts_platform_ig_account
  ON posts(instagram_account_id)
  WHERE platform = 'instagram';

-- 3. Posts: Published posts ordered by date (used by getPosts, analytics)
-- Supports: WHERE status = 'published' ORDER BY published_at DESC
-- Note: idx_posts_published_date already exists, this is a no-op
CREATE INDEX IF NOT EXISTS idx_posts_published_date
  ON posts(published_at DESC)
  WHERE status = 'published';

-- 4. Auto-post queue: Pending items for cron (used every minute by auto-post-worker)
-- Supports: WHERE status = 'pending' AND scheduled_for <= NOW()
-- Note: idx_auto_post_queue_pending already exists, this is a no-op
CREATE INDEX IF NOT EXISTS idx_auto_post_queue_pending
  ON auto_post_queue(scheduled_for)
  WHERE status = 'pending';

-- 5. Auto-post queue: Retry-pending items
-- Supports: WHERE status = 'retry_pending' AND next_retry_at <= NOW()
-- Note: idx_auto_post_queue_retry already exists from v2 migration (wider WHERE clause),
--       this creates a narrower partial index if the name is available
CREATE INDEX IF NOT EXISTS idx_auto_post_queue_retry_pending
  ON auto_post_queue(next_retry_at)
  WHERE status = 'retry_pending';

-- 6. Webhook events: Pending events for processors (queried every minute)
-- Supports: WHERE status = 'pending' ORDER BY received_at
-- Note: These use a status-based filter vs earlier processed_at IS NULL / processed = false
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'ig_webhook_events')
     AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'ig_webhook_events' AND column_name = 'status') THEN
    CREATE INDEX IF NOT EXISTS idx_ig_webhook_pending_received
      ON ig_webhook_events(received_at)
      WHERE status = 'pending';
  END IF;
END $$;

DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'threads_webhook_events')
     AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'threads_webhook_events' AND column_name = 'status') THEN
    CREATE INDEX IF NOT EXISTS idx_threads_webhook_pending_received
      ON threads_webhook_events(received_at)
      WHERE status = 'pending';
  END IF;
END $$;

-- 7 (Plan item 8). Account analytics: Daily lookup by account (most common query)
-- Supports: WHERE account_id = ? AND date >= ? ORDER BY date
-- Note: idx_account_analytics_account_date already exists, this is a no-op
CREATE INDEX IF NOT EXISTS idx_account_analytics_account_date
  ON account_analytics(account_id, date DESC);

-- 8 (Plan item 9). Competitor posts: Lookup by competitor ordered by created_at
-- Supports: WHERE competitor_id = ? ORDER BY created_at DESC
-- Note: idx_competitor_posts_competitor_created already exists from v2 migration, no-op
CREATE INDEX IF NOT EXISTS idx_competitor_posts_competitor_date
  ON competitor_posts(competitor_id, created_at DESC);

-- 9 (Plan item 10). Cron runs: Job health monitoring queries
-- Supports: WHERE job_name = ? ORDER BY started_at DESC LIMIT 10
-- Note: idx_cron_runs_job_started already exists from hardening migration, this adds alias
CREATE INDEX IF NOT EXISTS idx_cron_runs_job_recent
  ON cron_runs(job_name, started_at DESC);


-- ============================================================================
-- SECTION 2: RLS Policies (Plan Section 3.2)
-- ============================================================================
-- Enable RLS on tables that may have it disabled, add proper service role policies.
-- Uses DO blocks for safety — tables may not exist in all environments.

-- 2.1 ig_pending_containers
-- Note: RLS was enabled in 20260213000002, but original hardening DISABLED it.
-- Re-enable to ensure it's on, policy creation uses IF NOT EXISTS pattern.
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'ig_pending_containers') THEN
    ALTER TABLE ig_pending_containers ENABLE ROW LEVEL SECURITY;
    -- Policy already exists from 20260213000002 migration; skip if present
    IF NOT EXISTS (
      SELECT 1 FROM pg_policies
      WHERE schemaname = 'public' AND tablename = 'ig_pending_containers'
        AND policyname = 'Service role full access'
    ) THEN
      CREATE POLICY "Service role full access" ON ig_pending_containers
        FOR ALL USING (auth.jwt()->>'role' = 'service_role')
        WITH CHECK (auth.jwt()->>'role' = 'service_role');
    END IF;
  END IF;
END $$;

-- 2.2 threads_webhook_events
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'threads_webhook_events') THEN
    ALTER TABLE threads_webhook_events ENABLE ROW LEVEL SECURITY;
    IF NOT EXISTS (
      SELECT 1 FROM pg_policies
      WHERE schemaname = 'public' AND tablename = 'threads_webhook_events'
        AND policyname = 'Service role full access'
    ) THEN
      CREATE POLICY "Service role full access" ON threads_webhook_events
        FOR ALL USING (auth.jwt()->>'role' = 'service_role')
        WITH CHECK (auth.jwt()->>'role' = 'service_role');
    END IF;
  END IF;
END $$;

-- 2.3 cron_locks
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'cron_locks') THEN
    ALTER TABLE cron_locks ENABLE ROW LEVEL SECURITY;
    IF NOT EXISTS (
      SELECT 1 FROM pg_policies
      WHERE schemaname = 'public' AND tablename = 'cron_locks'
        AND policyname = 'Service role full access'
    ) THEN
      CREATE POLICY "Service role full access" ON cron_locks
        FOR ALL USING (auth.jwt()->>'role' = 'service_role')
        WITH CHECK (auth.jwt()->>'role' = 'service_role');
    END IF;
  END IF;
END $$;

-- 2.4 cron_runs
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'cron_runs') THEN
    ALTER TABLE cron_runs ENABLE ROW LEVEL SECURITY;
    IF NOT EXISTS (
      SELECT 1 FROM pg_policies
      WHERE schemaname = 'public' AND tablename = 'cron_runs'
        AND policyname = 'Service role full access'
    ) THEN
      CREATE POLICY "Service role full access" ON cron_runs
        FOR ALL USING (auth.jwt()->>'role' = 'service_role')
        WITH CHECK (auth.jwt()->>'role' = 'service_role');
    END IF;
  END IF;
END $$;

-- 2.5 Fix overly permissive group_analytics policies
-- Current state: "Service role full access to group analytics" uses USING(true) WITH CHECK(true)
-- Plan: Replace with proper service_role check + user read-own policy
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'group_analytics') THEN
    -- Drop the overly permissive "Service role full access to group analytics" policy
    IF EXISTS (
      SELECT 1 FROM pg_policies
      WHERE schemaname = 'public' AND tablename = 'group_analytics'
        AND policyname = 'Service role full access to group analytics'
    ) THEN
      DROP POLICY "Service role full access to group analytics" ON group_analytics;
    END IF;

    -- Also drop the plan-named policy if it exists from a previous run
    IF EXISTS (
      SELECT 1 FROM pg_policies
      WHERE schemaname = 'public' AND tablename = 'group_analytics'
        AND policyname = 'Service role manages group_analytics'
    ) THEN
      DROP POLICY "Service role manages group_analytics" ON group_analytics;
    END IF;

    -- Create proper service role policy (jwt check, not open USING(true))
    CREATE POLICY "Service role manages group_analytics" ON group_analytics
      FOR ALL USING (auth.jwt()->>'role' = 'service_role')
      WITH CHECK (auth.jwt()->>'role' = 'service_role');

    -- User read-own policy (may already exist from 20260212000003 migration)
    IF NOT EXISTS (
      SELECT 1 FROM pg_policies
      WHERE schemaname = 'public' AND tablename = 'group_analytics'
        AND policyname = 'Users read own group analytics'
    ) THEN
      CREATE POLICY "Users read own group analytics" ON group_analytics
        FOR SELECT USING (user_id = auth.uid()::text);
    END IF;
  END IF;
END $$;


-- ============================================================================
-- SECTION 3: CHECK Constraints on Status Fields (Plan Section 3.3)
-- ============================================================================
-- Uses DO blocks since ADD CONSTRAINT IF NOT EXISTS is not supported in all PG versions

-- 3.1 auto_post_queue.status
DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.table_constraints
    WHERE constraint_name = 'chk_auto_post_queue_status'
      AND table_name = 'auto_post_queue'
  ) THEN
    ALTER TABLE auto_post_queue
      ADD CONSTRAINT chk_auto_post_queue_status
      CHECK (status IN ('pending', 'queued', 'processing', 'published', 'failed', 'retry_pending', 'dead_letter', 'cancelled'));
  END IF;
END $$;

-- 3.2 ig_webhook_events.status (if status column exists)
DO $$ BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'ig_webhook_events' AND column_name = 'status'
  ) AND NOT EXISTS (
    SELECT 1 FROM information_schema.table_constraints
    WHERE constraint_name = 'chk_ig_webhook_events_status'
      AND table_name = 'ig_webhook_events'
  ) THEN
    ALTER TABLE ig_webhook_events
      ADD CONSTRAINT chk_ig_webhook_events_status
      CHECK (status IN ('pending', 'processing', 'processed', 'failed', 'retry_pending', 'dead_letter'));
  END IF;
END $$;

-- 3.3 threads_webhook_events.status (if status column exists)
DO $$ BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'threads_webhook_events' AND column_name = 'status'
  ) AND NOT EXISTS (
    SELECT 1 FROM information_schema.table_constraints
    WHERE constraint_name = 'chk_threads_webhook_events_status'
      AND table_name = 'threads_webhook_events'
  ) THEN
    ALTER TABLE threads_webhook_events
      ADD CONSTRAINT chk_threads_webhook_events_status
      CHECK (status IN ('pending', 'processing', 'processed', 'failed', 'retry_pending', 'dead_letter'));
  END IF;
END $$;

-- 3.4 posts.status
DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.table_constraints
    WHERE constraint_name = 'chk_posts_status'
      AND table_name = 'posts'
  ) THEN
    ALTER TABLE posts
      ADD CONSTRAINT chk_posts_status
      CHECK (status IN ('draft', 'scheduled', 'publishing', 'published', 'failed', 'deleted'));
  END IF;
END $$;


-- ============================================================================
-- SECTION 4: Cleanup Function (Plan Section 3.4)
-- ============================================================================

-- cleanup_old_cron_runs: Prevent unbounded cron_runs table growth
-- Default retention: 30 days
-- Usage: SELECT cleanup_old_cron_runs();        -- deletes rows older than 30 days
--        SELECT cleanup_old_cron_runs(7);        -- deletes rows older than 7 days

CREATE OR REPLACE FUNCTION cleanup_old_cron_runs(p_retention_days INT DEFAULT 30)
RETURNS INT AS $$
DECLARE
  v_deleted INT;
BEGIN
  DELETE FROM cron_runs
  WHERE started_at < NOW() - (p_retention_days || ' days')::INTERVAL;
  GET DIAGNOSTICS v_deleted = ROW_COUNT;
  RETURN v_deleted;
END;
$$ LANGUAGE plpgsql;

GRANT EXECUTE ON FUNCTION cleanup_old_cron_runs TO service_role;

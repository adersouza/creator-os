-- ============================================================================
-- Query Performance Optimization
--
-- Addresses 114 slow queries flagged by Supabase Query Performance.
--
-- 1. Add 3 composite indexes matching top query patterns
-- 2. Drop 5 exact-duplicate index pairs (keep one of each)
-- 3. Drop 6 prefix-redundant indexes (all with 0 scans)
-- 4. Trim Realtime publication from 10 → 5 tables
--    (WAL listener is 92.5% of total query time; fewer tables = less WAL churn)
-- ============================================================================

BEGIN;

-- ============================================================================
-- Part 1: Add missing composite indexes for top query patterns
-- ============================================================================

-- Posts list: ORDER BY published_at DESC NULLS LAST, created_at DESC
-- Covers queries #3 (71K calls, 7.8ms mean) and #18 (1.6K calls, 22ms mean)
CREATE INDEX IF NOT EXISTS idx_posts_user_published
  ON posts (user_id, published_at DESC NULLS LAST, created_at DESC);

-- Posts list filtered by platform: WHERE user_id=$1 AND platform=$2
-- Covers queries #7 (8.4K calls, 16.7ms) and #13 (8.4K calls, 6.9ms)
CREATE INDEX IF NOT EXISTS idx_posts_user_platform_published
  ON posts (user_id, platform, published_at DESC NULLS LAST, created_at DESC);

-- Accounts list: WHERE user_id=$1 ORDER BY created_at DESC
-- Covers query #9 (17K calls, 5.2ms) and #15 (6.8K calls, 6.6ms)
CREATE INDEX IF NOT EXISTS idx_accounts_user_created
  ON accounts (user_id, created_at DESC);

-- ============================================================================
-- Part 2: Drop exact-duplicate indexes (keep the first, drop the second)
-- ============================================================================

-- account_analytics: two identical (account_id, date DESC) indexes
DROP INDEX IF EXISTS idx_account_analytics_account_date;
-- keeping: idx_account_analytics_account_id_date

-- competitor_posts: two identical (competitor_id, created_at DESC) indexes
DROP INDEX IF EXISTS idx_competitor_posts_fetched;
-- keeping: idx_competitor_posts_competitor_created

-- threads_webhook_events: two identical (event_type, received_at DESC) indexes
DROP INDEX IF EXISTS idx_threads_webhook_type;
-- keeping: idx_threads_webhook_events_type

-- auto_post_queue: full index subsumes the partial index (both 0 scans)
-- keeping full: idx_auto_post_queue_engagement_fetch (status, posted_at, engagement_fetched_at)
DROP INDEX IF EXISTS idx_auto_post_queue_engagement_sync;

-- cron_runs: full index subsumes the partial WHERE status='failed' (both 0 scans)
-- keeping full: idx_cron_runs_job_started (job_name, started_at DESC)
DROP INDEX IF EXISTS idx_cron_runs_failed;

-- ============================================================================
-- Part 3: Drop prefix-redundant indexes (all 0 scans)
-- ============================================================================

-- account_analytics(account_id) — covered by unique (account_id, date) and composite
DROP INDEX IF EXISTS idx_account_analytics_account_id;

-- posts(account_id) — covered by idx_posts_account_created (account_id, created_at DESC)
DROP INDEX IF EXISTS idx_posts_account_id;

-- posts(user_id) — covered by new idx_posts_user_published and existing idx_posts_user_created
DROP INDEX IF EXISTS idx_posts_user_id;

-- posts(platform) — covered by idx_posts_platform_account (platform, account_id)
DROP INDEX IF EXISTS idx_posts_platform;

-- posts(status) — low-selectivity single column, covered by idx_posts_user_status
DROP INDEX IF EXISTS idx_posts_status;

-- accounts(created_at) — bare created_at without user_id is useless for RLS-filtered queries
DROP INDEX IF EXISTS accounts_created_at_idx;

-- ============================================================================
-- Part 4: Trim Realtime publication (biggest impact — 92.5% of query time)
--
-- KEEP (active frontend subscriptions):
--   sync_jobs        — real-time sync progress bars
--   notifications    — real-time notification delivery
--   posts            — real-time post status updates
--   auto_post_queue  — real-time queue monitoring
--   competitors      — competitorService subscribes to changes
--
-- REMOVE (no frontend subscriptions, rarely change):
--   auto_post_activity  — activity log, append-only
--   auto_post_state     — internal cron state
--   sent_replies        — historical record
--   workspace_members   — membership changes are rare
--   accounts            — account list changes are rare
-- ============================================================================

DO $$
DECLARE
  table_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'auto_post_activity',
    'auto_post_state',
    'sent_replies',
    'workspace_members',
    'accounts'
  ]
  LOOP
    IF EXISTS (
      SELECT 1
      FROM pg_publication_tables
      WHERE pubname = 'supabase_realtime'
        AND schemaname = 'public'
        AND tablename = table_name
    ) THEN
      EXECUTE format('ALTER PUBLICATION supabase_realtime DROP TABLE public.%I', table_name);
    END IF;
  END LOOP;
END $$;

COMMIT;

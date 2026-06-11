-- Performance Indexes Migration
-- Addresses high sequential scan counts identified via pg_stat_user_tables
-- These indexes will significantly reduce query times and database load

-- ============================================================================
-- ACCOUNTS TABLE (63 rows, 32k seq scans)
-- ============================================================================

DO $$
BEGIN
  IF to_regclass('public.accounts') IS NOT NULL THEN
    -- Index for user_id lookups (most common filter)
    EXECUTE 'CREATE INDEX IF NOT EXISTS idx_accounts_user_id ON public.accounts (user_id)';

    -- Index for threads_user_id lookups (API responses)
    EXECUTE 'CREATE INDEX IF NOT EXISTS idx_accounts_threads_user_id ON public.accounts (threads_user_id)';

    -- Composite index for user + status filtering
    EXECUTE 'CREATE INDEX IF NOT EXISTS idx_accounts_user_status ON public.accounts (user_id, status)';
  END IF;
END $$;

-- ============================================================================
-- POSTS TABLE (1,854 rows, 91k seq scans)
-- ============================================================================

DO $$
BEGIN
  IF to_regclass('public.posts') IS NOT NULL THEN
    -- Composite index for account + date (most common query pattern)
    EXECUTE 'CREATE INDEX IF NOT EXISTS idx_posts_account_created ON public.posts (account_id, created_at DESC)';

    -- Index for user + status filtering (draft, scheduled, published)
    EXECUTE 'CREATE INDEX IF NOT EXISTS idx_posts_user_status ON public.posts (user_id, status)';

    -- Index for scheduled posts lookup (cron job uses this)
    EXECUTE 'CREATE INDEX IF NOT EXISTS idx_posts_scheduled ON public.posts (status, scheduled_for) WHERE status = ''scheduled''';

    -- Composite for account + published_at (analytics queries)
    EXECUTE 'CREATE INDEX IF NOT EXISTS idx_posts_account_published ON public.posts (account_id, published_at DESC)';
  END IF;
END $$;

-- ============================================================================
-- ACCOUNT_ANALYTICS TABLE (2,297 rows, 1,903 seq scans)
-- ============================================================================

DO $$
BEGIN
  IF to_regclass('public.account_analytics') IS NOT NULL THEN
    -- Composite index for account + date range queries
    EXECUTE 'CREATE INDEX IF NOT EXISTS idx_account_analytics_account_date ON public.account_analytics (account_id, date DESC)';
  END IF;
END $$;

-- ============================================================================
-- AUTO_POST_CONFIG TABLE (1 row, 5.5k seq scans)
-- ============================================================================

DO $$
BEGIN
  IF to_regclass('public.auto_post_config') IS NOT NULL THEN
    -- Index for workspace_id lookups (unique constraint should exist, but add index)
    EXECUTE 'CREATE INDEX IF NOT EXISTS idx_auto_post_config_workspace ON public.auto_post_config (workspace_id)';
  END IF;
END $$;

-- ============================================================================
-- SYNC_JOBS TABLE (for Realtime subscriptions)
-- ============================================================================

DO $$
BEGIN
  IF to_regclass('public.sync_jobs') IS NOT NULL THEN
    -- Index for user's jobs lookup
    EXECUTE 'CREATE INDEX IF NOT EXISTS idx_sync_jobs_user_id ON public.sync_jobs (user_id)';

    -- Index for status filtering
    EXECUTE 'CREATE INDEX IF NOT EXISTS idx_sync_jobs_status ON public.sync_jobs (status)';
  END IF;
END $$;

-- ============================================================================
-- Run ANALYZE to update statistics
-- ============================================================================

DO $$
BEGIN
  IF to_regclass('public.accounts') IS NOT NULL THEN
    EXECUTE 'ANALYZE public.accounts';
  END IF;

  IF to_regclass('public.posts') IS NOT NULL THEN
    EXECUTE 'ANALYZE public.posts';
  END IF;

  IF to_regclass('public.account_analytics') IS NOT NULL THEN
    EXECUTE 'ANALYZE public.account_analytics';
  END IF;

  IF to_regclass('public.auto_post_config') IS NOT NULL THEN
    EXECUTE 'ANALYZE public.auto_post_config';
  END IF;

  IF to_regclass('public.sync_jobs') IS NOT NULL THEN
    EXECUTE 'ANALYZE public.sync_jobs';
  END IF;
END $$;

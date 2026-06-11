-- Migration: Add Missing Indexes for Multi-Account Performance
-- Date: 2026-01-21
-- Purpose: Improve query performance for 100+ accounts
--
-- These indexes address N+1 query bottlenecks identified in the multi-account audit.
-- They target frequently queried foreign keys that were missing indexes.

-- ============================================================================
-- 1. Sent Replies - Add account_id index
-- ============================================================================
-- Used when: Fetching replies sent from a specific account
-- Current behavior: Full table scan
-- After: Index lookup O(log n)

CREATE INDEX IF NOT EXISTS idx_sent_replies_account_id
ON public.sent_replies(account_id);

-- ============================================================================
-- 2. Mentions - Add account_id index (may already exist, using IF NOT EXISTS)
-- ============================================================================
-- Used when: Fetching mentions for a specific account
-- Current behavior: Full table scan
-- After: Index lookup O(log n)

CREATE INDEX IF NOT EXISTS idx_mentions_account_id
ON public.mentions(account_id);

-- ============================================================================
-- 3. Auto-Post Queue - Add composite index for common query pattern
-- ============================================================================
-- Used when: Finding pending posts for a workspace (cron job query)
-- Query pattern: WHERE workspace_id = X AND status = 'pending'
-- Current behavior: Scans full queue
-- After: Efficient composite index lookup

CREATE INDEX IF NOT EXISTS idx_auto_post_queue_workspace_status
ON public.auto_post_queue(workspace_id, status);

-- ============================================================================
-- 4. Accounts - Add index on token_expires_at for refresh cron
-- ============================================================================
-- Used when: Finding accounts with tokens expiring soon
-- Query pattern: WHERE token_expires_at < threshold AND is_active = true
-- Current behavior: Full accounts table scan
-- After: Efficient range scan

CREATE INDEX IF NOT EXISTS idx_accounts_token_expires_at
ON public.accounts(token_expires_at)
WHERE is_active = true;

-- ============================================================================
-- 5. Posts - Add composite index for scheduled posts cron
-- ============================================================================
-- Used when: Finding posts due for publishing
-- Query pattern: WHERE status = 'scheduled' AND scheduled_for <= now
-- Current behavior: Separate index scans, then intersection
-- After: Single composite index scan

CREATE INDEX IF NOT EXISTS idx_posts_scheduled_status
ON public.posts(scheduled_for, status)
WHERE status = 'scheduled';

-- ============================================================================
-- 6. Account Analytics - Add composite index for time-series queries
-- ============================================================================
-- Used when: Fetching analytics for multiple accounts over a date range
-- Query pattern: WHERE account_id IN (...) ORDER BY date DESC
-- Current behavior: Separate index scans
-- After: Efficient composite lookup

CREATE INDEX IF NOT EXISTS idx_account_analytics_account_date
ON public.account_analytics(account_id, date DESC);

-- ============================================================================
-- Verification Query (run manually to confirm indexes exist)
-- ============================================================================
-- SELECT indexname, tablename FROM pg_indexes
-- WHERE schemaname = 'public'
-- AND indexname LIKE 'idx_%'
-- ORDER BY tablename, indexname;

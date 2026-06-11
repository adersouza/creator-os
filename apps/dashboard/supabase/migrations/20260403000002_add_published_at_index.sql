-- Migration: Add performance indexes for hot-path queries
-- Date: 2026-04-03
-- Purpose: Add index for published_at queries (used in 6+ hot paths)
--          and partial index for threads_post_id lookups during sync
-- Note: Cannot use CONCURRENTLY inside Supabase implicit transaction.

-- Add index for published_at queries (used in 6+ hot paths)
CREATE INDEX IF NOT EXISTS idx_posts_published_at_desc
ON posts(published_at DESC NULLS LAST);

-- Add partial index for threads_post_id lookups during sync
CREATE INDEX IF NOT EXISTS idx_posts_account_threads_id
ON posts(account_id, threads_post_id)
WHERE threads_post_id IS NOT NULL;

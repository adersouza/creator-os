-- Ensure the get_fleet_metrics() published-post hot path has the covering
-- index from the 2026-05-06 production timeout audit.
--
-- This duplicates the earlier token/fleet migration intentionally. Prod status
-- showed the token and cleanup migrations applied while this index remained
-- open, so keep a standalone idempotent migration that cannot be skipped as a
-- side effect of token cleanup.

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_posts_fleet_metrics_covering_v2
  ON public.posts (user_id, status, published_at DESC)
  INCLUDE (
    account_id,
    instagram_account_id,
    platform,
    likes_count,
    views_count,
    replies_count,
    shares_count,
    ig_reach,
    ig_shares,
    ig_saved,
    ig_comment_count
  );

DROP INDEX CONCURRENTLY IF EXISTS public.idx_posts_fleet_metrics;
ALTER INDEX IF EXISTS public.idx_posts_fleet_metrics_covering_v2
  RENAME TO idx_posts_fleet_metrics;

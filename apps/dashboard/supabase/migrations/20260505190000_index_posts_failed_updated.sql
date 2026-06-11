-- ============================================================================
-- Index for get_fleet_metrics failed_agg CTE
-- ============================================================================
-- Date: 2026-05-05
-- Hot RPC: get_fleet_metrics(text, timestamptz, timestamptz) burns ~16M ms /
-- 14.8k calls (~1.1s mean) per pg_stat_statements. The base CTE is covered
-- by idx_posts_user_published_at_desc (partial WHERE status='published'),
-- but the failed_agg CTE filters on status IN ('failed','publish_failed')
-- + updated_at range with no matching index — falls back to bitmap-scan
-- + filter rather than direct index scan.
-- Partial index on the failure path so the second CTE plans cleanly.
-- ============================================================================

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_posts_user_failed_updated
  ON public.posts (user_id, updated_at DESC)
  WHERE status IN ('failed', 'publish_failed');

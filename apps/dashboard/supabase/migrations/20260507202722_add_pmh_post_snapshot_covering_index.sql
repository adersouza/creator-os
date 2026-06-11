-- Cover the hot useEngagementVelocity / fleet-metric history scan.
-- Before: nested-loop scan of pmh_post_hours required heap fetches for likes_count + replies_count
--         (200 posts × ~85 history rows = ~17k heap fetches → 1.4s on the heavy operator account).
-- After:  index-only scan, Heap Fetches: 0 → 115ms (12× speedup) on the same workload.

CREATE INDEX IF NOT EXISTS idx_pmh_post_snapshot_covering
  ON public.post_metric_history (post_id, snapshot_at DESC)
  INCLUDE (views_count, likes_count, replies_count);

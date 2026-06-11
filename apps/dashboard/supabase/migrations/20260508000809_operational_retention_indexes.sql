-- Operational retention + append-only table indexes.
--
-- scheduler_decisions is kept for recent v2 scheduler diagnostics only. The
-- schema stays in place for future scheduler work; this just drains cold rows
-- in bounded chunks before adding the BRIN index used by retention scans.

DO $$
DECLARE
  deleted_count integer;
BEGIN
  LOOP
    WITH doomed AS (
      SELECT id
      FROM public.scheduler_decisions
      WHERE created_at < NOW() - INTERVAL '3 days'
      ORDER BY created_at
      LIMIT 10000
    )
    DELETE FROM public.scheduler_decisions AS sd
    USING doomed
    WHERE sd.id = doomed.id;

    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    EXIT WHEN deleted_count = 0;

    PERFORM pg_sleep(0.1);
  END LOOP;
END $$;

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_scheduler_decisions_created_at_brin
  ON public.scheduler_decisions USING BRIN (created_at);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_post_metric_history_snapshot_at_brin
  ON public.post_metric_history USING BRIN (snapshot_at);

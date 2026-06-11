-- Rollback one day's cohort aggregates.
--
-- Usage (psql / Supabase SQL editor): replace :snapshot_date with the target
-- date. This wipes that snapshot only; the aggregator will re-write it on
-- the next 2 AM run (or on a manual trigger of analytics-pipeline).
--
--   psql "$DATABASE_URL" \
--     -v snapshot_date="'2026-04-26'" \
--     -f scripts/rollback-cohort-day.sql
--
-- Intended use: the aggregator wrote bad numbers (e.g., metric calc regression,
-- suppression threshold tuned wrong) and you want every CohortBulletChart to
-- fall back to the suppressed state until the next clean run. Does NOT touch
-- user_preferences.data_contribution_opted_in or the niche columns — those
-- are user-owned data and surviving the rollback is the right behavior.

BEGIN;

SELECT COUNT(*) AS rows_to_delete
FROM cohort_benchmarks
WHERE snapshot_date = :snapshot_date;

DELETE FROM cohort_benchmarks
WHERE snapshot_date = :snapshot_date;

-- Verify before commit. If the count is obviously wrong, ROLLBACK instead.
COMMIT;

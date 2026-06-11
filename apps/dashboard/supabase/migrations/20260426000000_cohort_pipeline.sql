-- B1: anonymized cohort pipeline — schema only.
--
-- Adds niche columns to accounts + instagram_accounts (user_niche = self-tag,
-- inferred_niche = AI fallback from posts.content_category mode) and creates
-- cohort_benchmarks, the daily aggregation table that the Wave 3 CohortBulletChart
-- reads from. Aggregation job + API handler ship in a follow-up PR once the
-- opt-in flywheel starts producing a usable sample base.
--
-- Privacy model: cohort_benchmarks stores only bucket aggregates (count + p25/
-- p50/p75/p90 per metric). No account IDs, user IDs, or post content. Write-time
-- k-anonymity is enforced by the aggregator (to be added): a row is only
-- inserted when account_count >= 30 AND user_count >= 10. Reads double-check
-- the same thresholds (defense in depth).

ALTER TABLE accounts
  ADD COLUMN IF NOT EXISTS user_niche TEXT,
  ADD COLUMN IF NOT EXISTS inferred_niche TEXT;

ALTER TABLE instagram_accounts
  ADD COLUMN IF NOT EXISTS user_niche TEXT,
  ADD COLUMN IF NOT EXISTS inferred_niche TEXT;

CREATE INDEX IF NOT EXISTS idx_accounts_niche
  ON accounts (COALESCE(user_niche, inferred_niche))
  WHERE user_niche IS NOT NULL OR inferred_niche IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_instagram_accounts_niche
  ON instagram_accounts (COALESCE(user_niche, inferred_niche))
  WHERE user_niche IS NOT NULL OR inferred_niche IS NOT NULL;

CREATE TABLE IF NOT EXISTS cohort_benchmarks (
  id BIGSERIAL PRIMARY KEY,
  snapshot_date DATE NOT NULL,
  platform TEXT NOT NULL CHECK (platform IN ('threads', 'instagram')),
  follower_tier TEXT NOT NULL CHECK (follower_tier IN ('0-1K', '1K-5K', '5K-10K', '10K-50K', '50K+')),
  niche TEXT NOT NULL,
  metric_name TEXT NOT NULL,
  account_count INTEGER NOT NULL,
  user_count INTEGER NOT NULL,
  p25 NUMERIC,
  p50 NUMERIC,
  p75 NUMERIC,
  p90 NUMERIC,
  mean NUMERIC,
  stddev NUMERIC,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (snapshot_date, platform, follower_tier, niche, metric_name)
);

CREATE INDEX IF NOT EXISTS idx_cohort_benchmarks_lookup
  ON cohort_benchmarks (platform, follower_tier, niche, snapshot_date DESC);

ALTER TABLE cohort_benchmarks ENABLE ROW LEVEL SECURITY;

-- Reads: any authenticated user (benchmarks are the public-to-members surface).
-- The cohort handler applies read-time k-anonymity on top; RLS does not need
-- to enforce thresholds because the aggregator guarantees rows below threshold
-- are never written.
DROP POLICY IF EXISTS "cohort_benchmarks_read_authenticated" ON cohort_benchmarks;
CREATE POLICY "cohort_benchmarks_read_authenticated"
  ON cohort_benchmarks FOR SELECT TO authenticated USING (true);

-- Writes: service role only via the cron aggregator. No write policy; the
-- service role bypasses RLS by design.

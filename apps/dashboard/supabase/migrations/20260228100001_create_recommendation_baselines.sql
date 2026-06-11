-- #567: Create recommendation_baselines table
-- Referenced by lowHangingFruit.ts (store/detect solved recs) and regressionDetector.ts

CREATE TABLE IF NOT EXISTS recommendation_baselines (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  account_id text NOT NULL,
  platform text NOT NULL DEFAULT 'threads',
  rec_id text NOT NULL,
  title text NOT NULL,
  icon text,
  category text NOT NULL,
  baseline_value real NOT NULL DEFAULT 0,
  threshold real NOT NULL DEFAULT 0,
  solved boolean NOT NULL DEFAULT false,
  solved_at timestamptz,
  post_opt_value real,
  regression_status text, -- 'regressed', 'faded', 'stable'
  regression_pct integer,
  regression_detected_at timestamptz,
  regression_expired boolean,
  updated_at timestamptz DEFAULT now(),
  created_at timestamptz DEFAULT now(),
  UNIQUE(account_id, platform, rec_id)
);

ALTER TABLE recommendation_baselines ENABLE ROW LEVEL SECURITY;

-- RLS: baselines are accessed by API (service role) on behalf of account owners.
-- The lowHangingFruit engine queries by account_id, which is already ownership-checked upstream.
-- Grant read access to authenticated users for their own accounts.
CREATE POLICY "Users read own baselines" ON recommendation_baselines
  FOR SELECT USING (
    account_id IN (
      SELECT id FROM accounts WHERE user_id = (SELECT auth.uid()::text)
    )
  );

-- Index for common queries
CREATE INDEX IF NOT EXISTS idx_rec_baselines_account_platform
  ON recommendation_baselines (account_id, platform);

CREATE INDEX IF NOT EXISTS idx_rec_baselines_solved
  ON recommendation_baselines (solved) WHERE solved = true;

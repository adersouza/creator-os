-- Account Health Snapshots — pre-computed per-account health metrics
-- Populated by six-hour-pipeline cron. Consumed by dashboard widgets:
-- AccountHealthRadar (anomaly alerts) and MoversAndShakers (growth leaderboard).
-- One row per user per account per period — upserted each cron run.

CREATE TABLE IF NOT EXISTS account_health_snapshots (
  id text PRIMARY KEY DEFAULT gen_random_uuid()::text,
  user_id text REFERENCES profiles(id) ON DELETE CASCADE NOT NULL,
  workspace_id text NOT NULL DEFAULT '',
  account_id text NOT NULL,
  account_name text NOT NULL DEFAULT '',
  platform text NOT NULL DEFAULT 'threads',

  -- Growth metrics
  followers_current integer DEFAULT 0,
  followers_previous integer DEFAULT 0,
  growth_pct numeric(8,2) DEFAULT 0,

  -- Reach / engagement
  reach_3day numeric DEFAULT 0,
  reach_14day numeric DEFAULT 0,
  reach_drop_pct numeric(8,2) DEFAULT 0,
  engagement_rate numeric(8,2) DEFAULT 0,
  group_avg_er numeric(8,2) DEFAULT 0,

  -- Posting activity
  days_since_last_post integer DEFAULT 0,
  posts_this_period integer DEFAULT 0,

  -- Anomaly flags
  has_anomaly boolean DEFAULT false,
  anomaly_severity text,
  anomaly_detail text,

  -- Metadata
  period_days integer NOT NULL DEFAULT 7,
  computed_at timestamptz DEFAULT now(),

  UNIQUE(user_id, account_id, period_days)
);

-- Fast dashboard queries: all snapshots for a user (sorted by recency)
CREATE INDEX IF NOT EXISTS idx_health_snapshots_user
  ON account_health_snapshots(user_id, computed_at DESC);

-- Alert-only queries: only fetch accounts with anomalies
CREATE INDEX IF NOT EXISTS idx_health_snapshots_anomaly
  ON account_health_snapshots(user_id, has_anomaly)
  WHERE has_anomaly = true;

-- Growth leaderboard: sort by growth_pct
CREATE INDEX IF NOT EXISTS idx_health_snapshots_growth
  ON account_health_snapshots(user_id, period_days, growth_pct DESC);

-- Enable RLS
ALTER TABLE account_health_snapshots ENABLE ROW LEVEL SECURITY;

-- Users can only read their own snapshots
CREATE POLICY "Users can read own health snapshots"
  ON account_health_snapshots FOR SELECT
  USING (auth.uid()::text = user_id);

-- Service role (cron) can insert/update
CREATE POLICY "Service role can manage health snapshots"
  ON account_health_snapshots FOR ALL
  USING (true)
  WITH CHECK (true);

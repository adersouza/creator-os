-- Account Metrics History — daily snapshots for long-term trending
-- Decoupled from account_analytics (which gets overwritten each sync);
-- this table is append-only (one row per account per day).

CREATE TABLE IF NOT EXISTS account_metrics_history (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id text NOT NULL,
  platform text NOT NULL DEFAULT 'threads',
  date date NOT NULL DEFAULT CURRENT_DATE,
  followers_count integer DEFAULT 0,
  total_views integer DEFAULT 0,
  total_likes integer DEFAULT 0,
  total_replies integer DEFAULT 0,
  total_reposts integer DEFAULT 0,
  total_shares integer DEFAULT 0,
  engagement_rate numeric DEFAULT 0,
  posts_count integer DEFAULT 0,
  created_at timestamptz DEFAULT now(),
  UNIQUE(account_id, date)
);

CREATE INDEX IF NOT EXISTS idx_amh_account_date ON account_metrics_history(account_id, date);
CREATE INDEX IF NOT EXISTS idx_amh_date ON account_metrics_history(date);

-- Enable RLS (policies added later once user_id join path is finalized)
ALTER TABLE account_metrics_history ENABLE ROW LEVEL SECURITY;

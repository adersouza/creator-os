-- Reconstructed from schema_migrations on prod (remote-only).
-- version: 20260406045537
-- applied-by: create_ghost_tables_batch2_final migration row


-- =============================================================================
-- Create 4 missing tables + 2 missing views
-- unified_link_roi and user_workspaces already exist as views — skip
-- =============================================================================

-- 1. demographics_snapshots
CREATE TABLE IF NOT EXISTS demographics_snapshots (
  id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
  account_id TEXT REFERENCES accounts(id) ON DELETE CASCADE,
  instagram_account_id UUID REFERENCES instagram_accounts(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  platform TEXT NOT NULL DEFAULT 'threads',
  date DATE NOT NULL,
  demographics_data JSONB,
  created_at TIMESTAMPTZ DEFAULT now()
);
ALTER TABLE demographics_snapshots ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Users access own demographics" ON demographics_snapshots;
CREATE POLICY "Users access own demographics" ON demographics_snapshots FOR ALL
  USING (auth.uid()::text = user_id) WITH CHECK (auth.uid()::text = user_id);
CREATE INDEX IF NOT EXISTS idx_demographics_snapshots_account ON demographics_snapshots(account_id, date DESC);
CREATE UNIQUE INDEX IF NOT EXISTS uq_demographics_account_date ON demographics_snapshots(account_id, date) WHERE account_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_demographics_ig_date ON demographics_snapshots(instagram_account_id, date) WHERE instagram_account_id IS NOT NULL;

-- 2. follower_history
CREATE TABLE IF NOT EXISTS follower_history (
  id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
  account_id TEXT NOT NULL,
  platform TEXT NOT NULL DEFAULT 'instagram',
  date DATE NOT NULL,
  follower_count BIGINT NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE (account_id, date)
);
ALTER TABLE follower_history ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Service can manage follower history" ON follower_history;
CREATE POLICY "Service can manage follower history" ON follower_history FOR ALL USING (true);
CREATE INDEX IF NOT EXISTS idx_follower_history_account_date ON follower_history(account_id, date);

-- 3. reply_response_times
CREATE TABLE IF NOT EXISTS reply_response_times (
  id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
  account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  platform TEXT NOT NULL DEFAULT 'threads',
  avg_response_mins NUMERIC,
  computed_at TIMESTAMPTZ DEFAULT now()
);
ALTER TABLE reply_response_times ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Service can manage reply times" ON reply_response_times;
CREATE POLICY "Service can manage reply times" ON reply_response_times FOR ALL USING (true);
CREATE INDEX IF NOT EXISTS idx_reply_response_times_account ON reply_response_times(account_id, platform, computed_at DESC);

-- 4. instagram_posts (view over posts table)
CREATE OR REPLACE VIEW instagram_posts AS
  SELECT * FROM posts WHERE platform = 'instagram';

-- 5. instagram_competitors (view over competitors table)
CREATE OR REPLACE VIEW instagram_competitors AS
  SELECT * FROM competitors WHERE platform = 'instagram';

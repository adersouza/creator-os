-- Applied via schema reconciliation 2026-03-07
-- Creates trend_discoveries table for trend-pipeline auto-poster

CREATE TABLE IF NOT EXISTS trend_discoveries (
  id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
  account_group_id TEXT NOT NULL REFERENCES account_groups(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  topic TEXT NOT NULL,
  topic_hash TEXT NOT NULL,
  context TEXT,
  relevance_score INT DEFAULT 0,
  source_data JSONB DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'discovered',
  discovered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  posted_at TIMESTAMPTZ,
  expired_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now()
);

DO $$ BEGIN
  ALTER TABLE trend_discoveries
    ADD CONSTRAINT trend_discoveries_account_group_id_topic_hash_unique UNIQUE (account_group_id, topic_hash);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_trend_discoveries_account_group_id ON trend_discoveries(account_group_id);
CREATE INDEX IF NOT EXISTS idx_trend_discoveries_user_id ON trend_discoveries(user_id);
CREATE INDEX IF NOT EXISTS idx_trend_discoveries_status_discovered ON trend_discoveries(status, discovered_at DESC);

ALTER TABLE trend_discoveries ENABLE ROW LEVEL SECURITY;

CREATE POLICY "service_role_full_access"
  ON trend_discoveries FOR ALL TO service_role
  USING (true) WITH CHECK (true);

CREATE POLICY "users_manage_own_discoveries"
  ON trend_discoveries FOR ALL
  USING ((select auth.uid())::text = user_id)
  WITH CHECK ((select auth.uid())::text = user_id);

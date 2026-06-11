-- Migration: Create trend_discoveries table
-- Phase 01, Plan 01: Trending Topics Auto-Poster foundation
-- Stores discovered trends with dedup constraint and audit trail

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

-- Dedup: one topic per account group
ALTER TABLE trend_discoveries
  ADD CONSTRAINT trend_discoveries_account_group_id_topic_hash_unique UNIQUE (account_group_id, topic_hash);

-- Indexes
CREATE INDEX idx_trend_discoveries_account_group_id ON trend_discoveries(account_group_id);
CREATE INDEX idx_trend_discoveries_user_id ON trend_discoveries(user_id);
CREATE INDEX idx_trend_discoveries_status_discovered ON trend_discoveries(status, discovered_at DESC);

-- Enable RLS
ALTER TABLE trend_discoveries ENABLE ROW LEVEL SECURITY;

-- Policy: service_role full access
CREATE POLICY "service_role_full_access"
  ON trend_discoveries
  FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

-- Policy: users manage own discoveries
CREATE POLICY "users_manage_own_discoveries"
  ON trend_discoveries
  FOR ALL
  USING (auth.uid()::text = user_id)
  WITH CHECK (auth.uid()::text = user_id);

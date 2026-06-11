-- Migration: Create trending_topic_config table
-- Phase 01, Plan 01: Trending Topics Auto-Poster foundation
-- Stores per-account-group config for trend scanning and auto-posting

CREATE TABLE IF NOT EXISTS trending_topic_config (
  id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
  account_group_id TEXT NOT NULL REFERENCES account_groups(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  keywords TEXT[] NOT NULL DEFAULT '{}',
  scan_frequency_hours INT NOT NULL DEFAULT 4,
  daily_post_cap INT NOT NULL DEFAULT 3,
  blocklist TEXT[] DEFAULT '{}',
  enabled BOOLEAN NOT NULL DEFAULT false,
  content_preferences JSONB DEFAULT '{}',
  last_scan_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- One config per account group
ALTER TABLE trending_topic_config
  ADD CONSTRAINT trending_topic_config_account_group_id_unique UNIQUE (account_group_id);

-- Indexes
CREATE INDEX idx_trending_topic_config_account_group_id ON trending_topic_config(account_group_id);
CREATE INDEX idx_trending_topic_config_user_id ON trending_topic_config(user_id);

-- Enable RLS
ALTER TABLE trending_topic_config ENABLE ROW LEVEL SECURITY;

-- Policy: service_role full access
CREATE POLICY "service_role_full_access"
  ON trending_topic_config
  FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

-- Policy: users manage own config
CREATE POLICY "users_manage_own_config"
  ON trending_topic_config
  FOR ALL
  USING (auth.uid()::text = user_id)
  WITH CHECK (auth.uid()::text = user_id);

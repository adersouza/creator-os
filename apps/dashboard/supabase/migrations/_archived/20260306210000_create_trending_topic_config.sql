-- Create trending_topic_config table for Empire-tier trend pipeline
CREATE TABLE IF NOT EXISTS trending_topic_config (
  id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
  account_group_id TEXT NOT NULL REFERENCES account_groups(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  enabled BOOLEAN NOT NULL DEFAULT true,
  keywords TEXT[] NOT NULL DEFAULT '{}',
  scan_frequency_hours INTEGER NOT NULL DEFAULT 4,
  daily_post_cap INTEGER NOT NULL DEFAULT 3,
  blocklist TEXT[] NOT NULL DEFAULT '{}',
  content_preferences JSONB NOT NULL DEFAULT '{}',
  last_scan_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (account_group_id)
);

-- RLS
ALTER TABLE trending_topic_config ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can manage their own trending configs"
  ON trending_topic_config
  FOR ALL
  USING (auth.uid()::text = user_id)
  WITH CHECK (auth.uid()::text = user_id);

-- Index for cron scanner (finds enabled configs due for scan)
CREATE INDEX idx_trending_topic_config_scan
  ON trending_topic_config (enabled, last_scan_at)
  WHERE enabled = true;

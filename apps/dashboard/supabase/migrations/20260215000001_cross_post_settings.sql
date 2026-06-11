-- Cross-post settings: auto-adapt and queue posts across platforms
CREATE TABLE IF NOT EXISTS cross_post_settings (
  id TEXT DEFAULT gen_random_uuid()::TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  enabled BOOLEAN DEFAULT false,
  delay_minutes INT DEFAULT 120,
  auto_approve BOOLEAN DEFAULT false,
  adaptation_style TEXT DEFAULT 'rewrite', -- 'minimal' | 'rewrite'
  auto_hashtags BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(workspace_id)
);

CREATE INDEX IF NOT EXISTS idx_cross_post_settings_workspace ON cross_post_settings(workspace_id);

-- RLS
ALTER TABLE cross_post_settings ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role full access on cross_post_settings"
  ON cross_post_settings
  FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

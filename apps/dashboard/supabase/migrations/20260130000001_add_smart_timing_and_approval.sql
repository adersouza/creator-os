-- Add smart timing column to auto_post_config
ALTER TABLE auto_post_config
  ADD COLUMN IF NOT EXISTS use_smart_timing BOOLEAN DEFAULT false;

-- Add approval workflow columns to posts
ALTER TABLE posts
  ADD COLUMN IF NOT EXISTS approval_status TEXT DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS approval_notes TEXT DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS approved_by UUID DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ DEFAULT NULL;

-- Create auto_reply_rules table
CREATE TABLE IF NOT EXISTS auto_reply_rules (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  account_id TEXT REFERENCES accounts(id) ON DELETE CASCADE,
  trigger_type TEXT NOT NULL CHECK (trigger_type IN ('keyword', 'first_message', 'mention')),
  trigger_pattern TEXT NOT NULL,
  reply_text TEXT NOT NULL,
  is_active BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_auto_reply_rules_workspace ON auto_reply_rules(workspace_id);
CREATE INDEX IF NOT EXISTS idx_auto_reply_rules_active ON auto_reply_rules(workspace_id, is_active);

-- Create listening_alerts table
CREATE TABLE IF NOT EXISTS listening_alerts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  keyword TEXT NOT NULL,
  alert_type TEXT NOT NULL CHECK (alert_type IN ('spike', 'threshold')),
  threshold_value INT DEFAULT 10,
  is_active BOOLEAN DEFAULT true,
  last_triggered_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_listening_alerts_workspace ON listening_alerts(workspace_id);

-- Create creator_links table
CREATE TABLE IF NOT EXISTS creator_links (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  url TEXT NOT NULL,
  label TEXT NOT NULL,
  click_count INT DEFAULT 0,
  is_active BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_creator_links_workspace ON creator_links(workspace_id);

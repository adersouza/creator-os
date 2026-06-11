-- Migration: Create auto_post_group_config table
-- Per-group posting configuration for group-aware batch auto-poster
-- Each group gets its own posting frequency, active hours, content queue

CREATE TABLE IF NOT EXISTS public.auto_post_group_config (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  group_id TEXT NOT NULL REFERENCES account_groups(id) ON DELETE CASCADE,
  posts_per_account_per_day INT NOT NULL DEFAULT 4,
  min_interval_minutes INT NOT NULL DEFAULT 90,
  active_hours_start INT NOT NULL DEFAULT 8,
  active_hours_end INT NOT NULL DEFAULT 22,
  timezone TEXT NOT NULL DEFAULT 'America/New_York',
  post_on_weekends BOOLEAN NOT NULL DEFAULT true,
  enabled BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(workspace_id, group_id)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_auto_post_group_config_workspace
ON public.auto_post_group_config(workspace_id);

CREATE INDEX IF NOT EXISTS idx_auto_post_group_config_group
ON public.auto_post_group_config(group_id);

-- RLS policies
ALTER TABLE public.auto_post_group_config ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role has full access to auto_post_group_config"
ON public.auto_post_group_config
FOR ALL
TO service_role
USING (true)
WITH CHECK (true);

-- Grant permissions
GRANT ALL ON TABLE public.auto_post_group_config TO service_role;

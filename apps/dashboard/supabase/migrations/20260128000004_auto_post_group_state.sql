-- Migration: Create auto_post_group_state table
-- Per-group rotation state for independent account cycling and queue position

CREATE TABLE IF NOT EXISTS public.auto_post_group_state (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  group_id TEXT NOT NULL REFERENCES account_groups(id) ON DELETE CASCADE,
  current_account_index INT NOT NULL DEFAULT 0,
  current_queue_index INT NOT NULL DEFAULT 0,
  posts_today INT NOT NULL DEFAULT 0,
  last_post_at TIMESTAMPTZ,
  last_reset_date DATE,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(workspace_id, group_id)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_auto_post_group_state_workspace
ON public.auto_post_group_state(workspace_id);

CREATE INDEX IF NOT EXISTS idx_auto_post_group_state_group
ON public.auto_post_group_state(group_id);

-- RLS policies
ALTER TABLE public.auto_post_group_state ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role has full access to auto_post_group_state"
ON public.auto_post_group_state
FOR ALL
TO service_role
USING (true)
WITH CHECK (true);

-- Grant permissions
GRANT ALL ON TABLE public.auto_post_group_state TO service_role;

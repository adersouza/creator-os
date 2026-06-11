-- #447: Add workspace_id to rss_feeds
-- ig_dm_templates and trend_keywords already have workspace_id columns.
-- rss_feeds was missing it.

ALTER TABLE public.rss_feeds
  ADD COLUMN IF NOT EXISTS workspace_id TEXT REFERENCES public.workspaces(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_rss_feeds_workspace ON public.rss_feeds(workspace_id)
  WHERE workspace_id IS NOT NULL;

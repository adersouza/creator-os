-- Campaign Factory export idempotency keys.
-- These keys make retries safe: Campaign Factory can reuse the same
-- ThreadsDashboard post/media/link rows instead of creating duplicate drafts.

ALTER TABLE public.campaign_factory_post_links
  ADD COLUMN IF NOT EXISTS draft_key TEXT,
  ADD COLUMN IF NOT EXISTS media_key TEXT,
  ADD COLUMN IF NOT EXISTS post_key TEXT,
  ADD COLUMN IF NOT EXISTS export_run_id TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS campaign_factory_post_links_user_post_key_uniq
  ON public.campaign_factory_post_links(user_id, post_key);

CREATE UNIQUE INDEX IF NOT EXISTS media_storage_path_uniq
  ON public.media(storage_path);

CREATE INDEX IF NOT EXISTS campaign_factory_post_links_export_run_idx
  ON public.campaign_factory_post_links(user_id, export_run_id)
  WHERE export_run_id IS NOT NULL;

-- Add JSONB column for configurable content filter patterns.
-- Stores an array of { pattern, label } objects that the queue-fill
-- filter evaluates BEFORE inserting AI / competitor-copy posts.
-- Updatable at runtime via upsert_workspace_config — no redeploy needed.

ALTER TABLE public.auto_post_config
  ADD COLUMN IF NOT EXISTS content_filter_patterns JSONB;

-- Also store filter settings (max length, max emoji count)
ALTER TABLE public.auto_post_config
  ADD COLUMN IF NOT EXISTS content_filter_max_length INTEGER DEFAULT 200;

ALTER TABLE public.auto_post_config
  ADD COLUMN IF NOT EXISTS content_filter_max_emojis INTEGER DEFAULT 2;

COMMENT ON COLUMN public.auto_post_config.content_filter_patterns IS
  'Array of {pattern, label} objects — regex patterns that reject queue items before insertion. Evaluated case-insensitive.';
COMMENT ON COLUMN public.auto_post_config.content_filter_max_length IS
  'Max character length for auto-posted content. Posts exceeding this are rejected at queue fill time.';
COMMENT ON COLUMN public.auto_post_config.content_filter_max_emojis IS
  'Max emoji count allowed in auto-posted content. Posts exceeding this are rejected at queue fill time.';

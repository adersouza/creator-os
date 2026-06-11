-- Content Library phases 1-2: recent usage, template variables, collections.

ALTER TABLE public.media
  ADD COLUMN IF NOT EXISTS last_used_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_media_user_last_used
  ON public.media(user_id, last_used_at DESC NULLS LAST, created_at DESC);

ALTER TABLE public.post_templates
  ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT now(),
  ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS idx_post_templates_recent_usage
  ON public.post_templates(user_id, times_used DESC, updated_at DESC NULLS LAST, created_at DESC);

CREATE TABLE IF NOT EXISTS public.content_collections (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  item_ids JSONB DEFAULT '[]',
  created_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE public.content_collections ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users manage own collections" ON public.content_collections;
CREATE POLICY "Users manage own collections" ON public.content_collections FOR ALL
  USING ((SELECT auth.uid())::text = user_id)
  WITH CHECK ((SELECT auth.uid())::text = user_id);

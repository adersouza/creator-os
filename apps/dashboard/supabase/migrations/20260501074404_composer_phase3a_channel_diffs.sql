CREATE TABLE IF NOT EXISTS public.post_channel_diffs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  draft_id TEXT NOT NULL,
  platform TEXT NOT NULL CHECK (platform IN ('threads','instagram_feed','instagram_story','instagram_reel')),
  divergence_type TEXT CHECK (divergence_type IN ('hook_changed','cta_moved','length_trim','tone_shift','custom')),
  master_caption TEXT NOT NULL,
  variant_caption TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'unresolved' CHECK (status IN ('unresolved','accepted','reverted')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  resolved_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_post_channel_diffs_draft ON public.post_channel_diffs(draft_id, status);
ALTER TABLE public.post_channel_diffs ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Users manage own diffs" ON public.post_channel_diffs;
CREATE POLICY "Users manage own diffs" ON public.post_channel_diffs FOR ALL USING (auth.uid()::text = user_id) WITH CHECK (auth.uid()::text = user_id);

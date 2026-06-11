CREATE TABLE IF NOT EXISTS public.post_variants (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  draft_id TEXT,
  post_id TEXT REFERENCES public.posts(id),
  variant_label TEXT NOT NULL CHECK (variant_label IN ('A','B','C')),
  content TEXT NOT NULL,
  variant_type TEXT CHECK (variant_type IN ('hook','pov','listicle','question','story')),
  predicted_score INT CHECK (predicted_score BETWEEN 0 AND 100),
  predicted_confidence NUMERIC(3,2),
  reasoning_json JSONB DEFAULT '{}'::jsonb,
  live_views_count BIGINT,
  live_engagement_rate NUMERIC(5,4),
  promoted_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_post_variants_draft ON public.post_variants(draft_id);
CREATE INDEX IF NOT EXISTS idx_post_variants_post ON public.post_variants(post_id);

ALTER TABLE public.post_variants ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users manage own variants" ON public.post_variants;
CREATE POLICY "Users manage own variants"
  ON public.post_variants
  FOR ALL
  USING (auth.uid()::text = user_id)
  WITH CHECK (auth.uid()::text = user_id);

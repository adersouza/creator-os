CREATE TABLE IF NOT EXISTS public.voice_context_files (
  account_group_id TEXT PRIMARY KEY REFERENCES public.account_groups(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  content TEXT NOT NULL,
  version INT NOT NULL DEFAULT 1,
  banned_patterns TEXT[],
  audience TEXT,
  top_patterns JSONB DEFAULT '[]'::jsonb,
  last_edited_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.voice_context_files ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Users manage own voice files" ON public.voice_context_files;
CREATE POLICY "Users manage own voice files" ON public.voice_context_files FOR ALL USING (auth.uid()::text = user_id) WITH CHECK (auth.uid()::text = user_id);

INSERT INTO public.voice_context_files (account_group_id, user_id, content, top_patterns)
SELECT
  id,
  user_id,
  COALESCE(voice_profile::text, ''),
  COALESCE(voice_profile->'top_patterns', '[]'::jsonb)
FROM public.account_groups
WHERE voice_profile IS NOT NULL
ON CONFLICT (account_group_id) DO NOTHING;

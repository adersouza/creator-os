CREATE TABLE IF NOT EXISTS public.inbox_ai_suggestions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  conversation_key TEXT NOT NULL,
  suggestion_text TEXT NOT NULL,
  reasoning TEXT,
  alternatives JSONB NOT NULL DEFAULT '[]'::jsonb,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'accepted', 'rejected')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_inbox_ai_suggestions_lookup
  ON public.inbox_ai_suggestions(user_id, conversation_key, status, created_at DESC);

ALTER TABLE public.inbox_ai_suggestions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users manage own inbox ai suggestions"
  ON public.inbox_ai_suggestions;
CREATE POLICY "Users manage own inbox ai suggestions"
  ON public.inbox_ai_suggestions
  FOR ALL
  USING (auth.uid()::text = user_id)
  WITH CHECK (auth.uid()::text = user_id);

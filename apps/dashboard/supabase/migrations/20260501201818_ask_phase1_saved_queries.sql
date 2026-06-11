CREATE TABLE IF NOT EXISTS public.saved_nl_queries (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  prompt TEXT NOT NULL,
  spec JSONB NOT NULL,
  name TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE public.saved_nl_queries ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users manage own queries" ON public.saved_nl_queries
  FOR ALL
  USING ((SELECT auth.uid())::text = user_id)
  WITH CHECK ((SELECT auth.uid())::text = user_id);

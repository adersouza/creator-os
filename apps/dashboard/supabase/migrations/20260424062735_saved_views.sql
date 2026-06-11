-- Saved views — per-user named filter presets for the Analytics page.
-- Wave 2 / Auto-Insights milestone: operators get a one-click restore of
-- platform + timeframe + scoped account so agency managers can jump between
-- views without re-setting every control.
--
-- Personal-scope for v1; workspace-shared views may follow in a later
-- migration when agency role semantics are finalized.

CREATE TABLE IF NOT EXISTS public.saved_views (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  name TEXT NOT NULL CHECK (char_length(name) BETWEEN 1 AND 80),
  -- scope keeps the door open for 'dashboard', 'calendar', etc. without
  -- needing a new table per surface.
  scope TEXT NOT NULL DEFAULT 'analytics' CHECK (scope IN ('analytics')),
  filters JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS saved_views_user_scope_idx
  ON public.saved_views(user_id, scope, updated_at DESC);

-- Uniqueness on (user_id, scope, lower(name)) would be nicer but the CHECK
-- already caps length — app-side validation handles the rest.

ALTER TABLE public.saved_views ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "own_saved_views" ON public.saved_views;
CREATE POLICY "own_saved_views" ON public.saved_views
  FOR ALL
  USING (auth.uid()::text = user_id)
  WITH CHECK (auth.uid()::text = user_id);

-- Refresh updated_at on UPDATE.
CREATE OR REPLACE FUNCTION public.set_saved_views_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at := NOW();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS saved_views_updated_at ON public.saved_views;
CREATE TRIGGER saved_views_updated_at
  BEFORE UPDATE ON public.saved_views
  FOR EACH ROW
  EXECUTE FUNCTION public.set_saved_views_updated_at();

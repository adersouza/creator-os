-- W1-C uniqueness guardrail: pg_trgm + banned_phrases + trigram dupe RPC
-- Adds cheap pre-filters before the Gemini embedding gate so trivial
-- duplicates and shadowban-triggering phrases reject without hitting the
-- embedding API. Gemini gate (embeddingGate.ts) runs unchanged after.

CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA extensions;

-- ============================================================================
-- banned_phrases — workspace-scoped shadowban / brand-safety filter list
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.banned_phrases (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id TEXT NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
  phrase TEXT NOT NULL,
  pattern_type TEXT NOT NULL DEFAULT 'substring'
    CHECK (pattern_type IN ('substring', 'regex', 'exact')),
  severity TEXT NOT NULL DEFAULT 'block'
    CHECK (severity IN ('block', 'warn')),
  reason TEXT,
  created_by TEXT REFERENCES public.profiles(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS banned_phrases_workspace_phrase_uniq
  ON public.banned_phrases (workspace_id, lower(phrase), pattern_type);
CREATE INDEX IF NOT EXISTS banned_phrases_workspace_id_idx
  ON public.banned_phrases (workspace_id);

CREATE OR REPLACE FUNCTION public.update_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS update_banned_phrases_updated_at ON public.banned_phrases;
CREATE TRIGGER update_banned_phrases_updated_at
  BEFORE UPDATE ON public.banned_phrases
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

ALTER TABLE public.banned_phrases ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "banned_phrases_members_read" ON public.banned_phrases;
CREATE POLICY "banned_phrases_members_read" ON public.banned_phrases
  FOR SELECT
  USING (is_workspace_member(workspace_id, (SELECT auth.uid())::text));

DROP POLICY IF EXISTS "banned_phrases_owner_write" ON public.banned_phrases;
CREATE POLICY "banned_phrases_owner_write" ON public.banned_phrases
  FOR ALL
  USING (is_workspace_owner(workspace_id, (SELECT auth.uid())::text))
  WITH CHECK (is_workspace_owner(workspace_id, (SELECT auth.uid())::text));

-- ============================================================================
-- check_trigram_dupe(workspace_id, content, threshold) -> {id, similarity}
-- Returns the single most-similar recent post if it exceeds threshold, else
-- an empty set. Called by prefilterGate before the embedding gate.
-- Return type matches auto_post_queue.id (TEXT).
-- ============================================================================
CREATE OR REPLACE FUNCTION public.check_trigram_dupe(
  p_workspace_id TEXT,
  p_content TEXT,
  p_threshold REAL DEFAULT 0.7
) RETURNS TABLE(matched_id TEXT, matched_similarity REAL)
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = public, extensions
AS $$
BEGIN
  RETURN QUERY
  SELECT q.id, extensions.similarity(q.content, p_content)::REAL AS sim
  FROM public.auto_post_queue q
  WHERE q.workspace_id = p_workspace_id
    AND q.status IN ('published', 'pending', 'queued')
    AND q.content IS NOT NULL
    AND LENGTH(q.content) > 0
    AND extensions.similarity(q.content, p_content) >= p_threshold
  ORDER BY extensions.similarity(q.content, p_content) DESC
  LIMIT 1;
END;
$$;

REVOKE ALL ON FUNCTION public.check_trigram_dupe(TEXT, TEXT, REAL) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.check_trigram_dupe(TEXT, TEXT, REAL) TO authenticated, service_role;

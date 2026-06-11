-- Reconstructed from schema_migrations on prod (remote-only).
-- version: 20260417024945
-- applied-by: fix_check_trigram_dupe_return_type migration row

-- Fix return type: auto_post_queue.id is TEXT, not UUID.
DROP FUNCTION IF EXISTS public.check_trigram_dupe(TEXT, TEXT, REAL);

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

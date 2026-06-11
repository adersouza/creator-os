ALTER TABLE IF EXISTS public.autoposter_post_performance_facts
  ADD COLUMN IF NOT EXISTS question_subtype TEXT;

ALTER TABLE IF EXISTS public.autoposter_winner_patterns
  ADD COLUMN IF NOT EXISTS question_subtype TEXT,
  ADD COLUMN IF NOT EXISTS clone_family TEXT;

CREATE INDEX IF NOT EXISTS autoposter_performance_question_subtype_idx
  ON public.autoposter_post_performance_facts(question_subtype, views_24h DESC)
  WHERE question_subtype IS NOT NULL;

CREATE INDEX IF NOT EXISTS autoposter_winner_patterns_clone_family_idx
  ON public.autoposter_winner_patterns(clone_family, views_24h DESC)
  WHERE clone_family IS NOT NULL;

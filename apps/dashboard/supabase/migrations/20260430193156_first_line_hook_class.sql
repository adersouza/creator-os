-- First-line hook NLP classification.
--
-- Mockup: dashboard-research-validated-2026.html R6 ("First-line hook NLP ·
-- 30d") — surfaces caption opening lines bucketed by hook archetype
-- (question, list, contrarian, story, stat, command, etc.) and shows which
-- archetypes drive the most reach.
--
-- Approach: classifier output goes on posts directly so the analytics handler
-- can group with a simple GROUP BY. Classifier is a small Gemini prompt run
-- inside the existing analytics-pipeline content-classification phase
-- (api/_lib/cron/analytics-pipeline/content-classification.ts) — same
-- pattern as `content_category`.
--
-- Writer expectations (out of scope here):
--   - hook_class: enum-ish values from a fixed taxonomy.
--   - hook_class_confidence: 0-1, classifier's self-rated confidence.
--   - hook_classified_at: when the classifier last ran for this post.
-- The taxonomy lives in the classifier prompt — no DB enum so the prompt
-- can evolve without migrations.

ALTER TABLE public.posts
  ADD COLUMN IF NOT EXISTS hook_class TEXT,
  ADD COLUMN IF NOT EXISTS hook_class_confidence NUMERIC,
  ADD COLUMN IF NOT EXISTS hook_classified_at TIMESTAMPTZ;

-- For the analytics handler aggregation (GROUP BY hook_class, AVG reach).
CREATE INDEX IF NOT EXISTS posts_hook_class_published_at_idx
  ON public.posts (hook_class, published_at DESC)
  WHERE hook_class IS NOT NULL;

COMMENT ON COLUMN public.posts.hook_class IS
  'NLP classifier output for the caption opening line. Free-form taxonomy from the classifier prompt (question, list, contrarian, story, stat, command, …). NULL = not yet classified. Powers first-line hook NLP tile (mockup dashboard-research-validated R6).';
COMMENT ON COLUMN public.posts.hook_class_confidence IS
  'Classifier self-rated confidence in 0-1. Below 0.5 should be excluded from aggregations.';
COMMENT ON COLUMN public.posts.hook_classified_at IS
  'When the classifier last ran for this post. Re-classify if NULL or older than 30 days (taxonomy-drift guard).';

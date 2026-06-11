BEGIN;

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions;

CREATE TABLE IF NOT EXISTS public.account_dna (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

  workspace_id TEXT NOT NULL,
  group_id TEXT,
  account_id TEXT NOT NULL,

  version INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL DEFAULT 'draft',
  confidence NUMERIC NOT NULL DEFAULT 0,

  archetype TEXT NOT NULL,
  sub_archetype TEXT,
  follower_promise TEXT NOT NULL,

  identity_summary TEXT NOT NULL,
  backstory_facts JSONB NOT NULL DEFAULT '[]'::jsonb,
  recurring_motifs JSONB NOT NULL DEFAULT '[]'::jsonb,
  recurring_situations JSONB NOT NULL DEFAULT '[]'::jsonb,
  signature_beliefs JSONB NOT NULL DEFAULT '[]'::jsonb,

  primary_topics JSONB NOT NULL DEFAULT '[]'::jsonb,
  secondary_topics JSONB NOT NULL DEFAULT '[]'::jsonb,
  taboo_topics JSONB NOT NULL DEFAULT '[]'::jsonb,

  signature_phrases JSONB NOT NULL DEFAULT '[]'::jsonb,
  banned_phrases JSONB NOT NULL DEFAULT '[]'::jsonb,
  vocabulary_fingerprint JSONB NOT NULL DEFAULT '{}'::jsonb,

  emoji_policy TEXT NOT NULL DEFAULT 'minimal',
  punctuation_habits JSONB NOT NULL DEFAULT '{}'::jsonb,
  casing_style TEXT NOT NULL DEFAULT 'lowercase',
  average_length_min INTEGER NOT NULL DEFAULT 20,
  average_length_max INTEGER NOT NULL DEFAULT 140,

  emotional_baseline TEXT NOT NULL,
  allowed_mood_range JSONB NOT NULL DEFAULT '[]'::jsonb,
  cta_posture TEXT NOT NULL DEFAULT 'soft',
  controversy_level INTEGER NOT NULL DEFAULT 2,
  humor_level INTEGER NOT NULL DEFAULT 2,
  storytelling_tendency INTEGER NOT NULL DEFAULT 2,
  vulnerability_level INTEGER NOT NULL DEFAULT 2,
  flirt_level INTEGER NOT NULL DEFAULT 2,

  style_embedding extensions.vector(1536),
  topic_embedding extensions.vector(1536),
  voice_embedding extensions.vector(1536),

  source_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
  generated_from TEXT NOT NULL DEFAULT 'backfill',

  last_scored_at TIMESTAMPTZ,
  last_refreshed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT account_dna_status_check
    CHECK (status IN ('draft', 'active', 'retired')),
  CONSTRAINT account_dna_confidence_check
    CHECK (confidence BETWEEN 0 AND 1),
  CONSTRAINT account_dna_emoji_policy_check
    CHECK (emoji_policy IN ('none', 'minimal', 'moderate', 'heavy')),
  CONSTRAINT account_dna_casing_style_check
    CHECK (casing_style IN ('lowercase', 'sentence', 'mixed', 'chaotic')),
  CONSTRAINT account_dna_cta_posture_check
    CHECK (cta_posture IN ('none', 'soft', 'direct', 'teasing', 'salesy')),
  CONSTRAINT account_dna_length_bounds_check
    CHECK (average_length_min >= 0 AND average_length_max >= average_length_min),
  CONSTRAINT account_dna_level_bounds_check
    CHECK (
      controversy_level BETWEEN 0 AND 5 AND
      humor_level BETWEEN 0 AND 5 AND
      storytelling_tendency BETWEEN 0 AND 5 AND
      vulnerability_level BETWEEN 0 AND 5 AND
      flirt_level BETWEEN 0 AND 5
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS account_dna_one_active_per_account
  ON public.account_dna(account_id)
  WHERE status = 'active';

CREATE INDEX IF NOT EXISTS account_dna_workspace_group_idx
  ON public.account_dna(workspace_id, group_id, account_id);

CREATE INDEX IF NOT EXISTS account_dna_voice_embedding_idx
  ON public.account_dna
  USING ivfflat (voice_embedding extensions.vector_cosine_ops)
  WHERE voice_embedding IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.account_dna_examples (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

  workspace_id TEXT NOT NULL,
  group_id TEXT,
  account_id TEXT NOT NULL,
  dna_id UUID NOT NULL REFERENCES public.account_dna(id) ON DELETE CASCADE,

  source_type TEXT NOT NULL,
  source_id TEXT,
  content TEXT NOT NULL,

  example_type TEXT NOT NULL,
  weight NUMERIC NOT NULL DEFAULT 1,

  hook_type TEXT,
  topic_label TEXT,
  format_type TEXT,
  emotional_frame TEXT,
  reply_mechanism TEXT,
  content_length_bucket TEXT,
  media_style TEXT,

  dna_fit_score NUMERIC,
  voice_fit_score NUMERIC,
  topic_fit_score NUMERIC,
  mood_fit_score NUMERIC,
  uniqueness_score NUMERIC,
  genericness_score NUMERIC,

  reason TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT account_dna_examples_source_type_check
    CHECK (source_type IN (
      'historical_post',
      'top_performer',
      'operator_seed',
      'generated_candidate',
      'rejected_candidate',
      'manual_note'
    )),
  CONSTRAINT account_dna_examples_example_type_check
    CHECK (example_type IN (
      'canonical',
      'good',
      'bad',
      'borderline',
      'anti_example',
      'signature'
    )),
  CONSTRAINT account_dna_examples_score_bounds_check
    CHECK (
      (dna_fit_score IS NULL OR dna_fit_score BETWEEN 0 AND 100) AND
      (voice_fit_score IS NULL OR voice_fit_score BETWEEN 0 AND 100) AND
      (topic_fit_score IS NULL OR topic_fit_score BETWEEN 0 AND 100) AND
      (mood_fit_score IS NULL OR mood_fit_score BETWEEN 0 AND 100) AND
      (uniqueness_score IS NULL OR uniqueness_score BETWEEN 0 AND 100) AND
      (genericness_score IS NULL OR genericness_score BETWEEN 0 AND 100)
    )
);

CREATE INDEX IF NOT EXISTS account_dna_examples_account_idx
  ON public.account_dna_examples(account_id, example_type, created_at DESC);

CREATE INDEX IF NOT EXISTS account_dna_examples_dna_idx
  ON public.account_dna_examples(dna_id, weight DESC);

CREATE TABLE IF NOT EXISTS public.account_dna_rules (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

  workspace_id TEXT NOT NULL,
  group_id TEXT,
  account_id TEXT NOT NULL,
  dna_id UUID NOT NULL REFERENCES public.account_dna(id) ON DELETE CASCADE,

  rule_type TEXT NOT NULL,
  rule_value TEXT NOT NULL,
  rule_payload JSONB NOT NULL DEFAULT '{}'::jsonb,

  action TEXT NOT NULL,
  severity TEXT NOT NULL DEFAULT 'medium',
  weight NUMERIC NOT NULL DEFAULT 1,

  reason TEXT,
  created_by TEXT,
  expires_at TIMESTAMPTZ,

  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT account_dna_rules_rule_type_check
    CHECK (rule_type IN (
      'required_phrase',
      'preferred_phrase',
      'banned_phrase',
      'owned_phrase',
      'topic_allow',
      'topic_limit',
      'topic_ban',
      'hook_allow',
      'hook_limit',
      'hook_ban',
      'mood_allow',
      'mood_ban',
      'format_allow',
      'format_ban',
      'length_limit',
      'emoji_policy',
      'punctuation_policy',
      'cta_policy',
      'sibling_avoid'
    )),
  CONSTRAINT account_dna_rules_action_check
    CHECK (action IN ('boost', 'penalize', 'block', 'require', 'review')),
  CONSTRAINT account_dna_rules_severity_check
    CHECK (severity IN ('low', 'medium', 'high', 'critical'))
);

CREATE INDEX IF NOT EXISTS account_dna_rules_account_idx
  ON public.account_dna_rules(account_id, rule_type, action);

CREATE INDEX IF NOT EXISTS account_dna_rules_scope_idx
  ON public.account_dna_rules(workspace_id, group_id, rule_type, expires_at);

CREATE TABLE IF NOT EXISTS public.account_uniqueness_metrics (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

  workspace_id TEXT NOT NULL,
  group_id TEXT,
  account_id TEXT NOT NULL,
  compared_account_id TEXT,

  window_start TIMESTAMPTZ NOT NULL,
  window_end TIMESTAMPTZ NOT NULL,

  uniqueness_score NUMERIC NOT NULL,
  voice_similarity_score NUMERIC NOT NULL,
  topic_similarity_score NUMERIC NOT NULL,
  hook_similarity_score NUMERIC NOT NULL,
  phrase_collision_score NUMERIC NOT NULL,
  opener_collision_score NUMERIC NOT NULL,
  sibling_collision_score NUMERIC NOT NULL,
  drift_score NUMERIC NOT NULL,
  genericness_score NUMERIC NOT NULL,

  owned_phrase_hits JSONB NOT NULL DEFAULT '[]'::jsonb,
  collided_phrases JSONB NOT NULL DEFAULT '[]'::jsonb,
  collided_hooks JSONB NOT NULL DEFAULT '[]'::jsonb,
  collided_topics JSONB NOT NULL DEFAULT '[]'::jsonb,

  sample_post_count INTEGER NOT NULL DEFAULT 0,
  compared_post_count INTEGER NOT NULL DEFAULT 0,

  decision TEXT NOT NULL DEFAULT 'healthy',
  reason TEXT,

  computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT account_uniqueness_decision_check
    CHECK (decision IN ('healthy', 'watch', 'drifting', 'colliding', 'generic')),
  CONSTRAINT account_uniqueness_score_bounds_check
    CHECK (
      uniqueness_score BETWEEN 0 AND 100 AND
      voice_similarity_score BETWEEN 0 AND 100 AND
      topic_similarity_score BETWEEN 0 AND 100 AND
      hook_similarity_score BETWEEN 0 AND 100 AND
      phrase_collision_score BETWEEN 0 AND 100 AND
      opener_collision_score BETWEEN 0 AND 100 AND
      sibling_collision_score BETWEEN 0 AND 100 AND
      drift_score BETWEEN 0 AND 100 AND
      genericness_score BETWEEN 0 AND 100
    )
);

CREATE INDEX IF NOT EXISTS account_uniqueness_latest_idx
  ON public.account_uniqueness_metrics(account_id, computed_at DESC);

CREATE INDEX IF NOT EXISTS account_uniqueness_group_idx
  ON public.account_uniqueness_metrics(workspace_id, group_id, computed_at DESC);

ALTER TABLE IF EXISTS public.auto_post_queue
  ADD COLUMN IF NOT EXISTS dna_id UUID REFERENCES public.account_dna(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS dna_version INTEGER,
  ADD COLUMN IF NOT EXISTS dna_fit_score NUMERIC,
  ADD COLUMN IF NOT EXISTS voice_fit_score NUMERIC,
  ADD COLUMN IF NOT EXISTS topic_fit_score NUMERIC,
  ADD COLUMN IF NOT EXISTS mood_fit_score NUMERIC,
  ADD COLUMN IF NOT EXISTS uniqueness_score NUMERIC,
  ADD COLUMN IF NOT EXISTS sibling_collision_score NUMERIC,
  ADD COLUMN IF NOT EXISTS genericness_score NUMERIC,
  ADD COLUMN IF NOT EXISTS dna_decision TEXT,
  ADD COLUMN IF NOT EXISTS dna_reasons JSONB;

ALTER TABLE IF EXISTS public.posts
  ADD COLUMN IF NOT EXISTS dna_id UUID REFERENCES public.account_dna(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS dna_version INTEGER,
  ADD COLUMN IF NOT EXISTS dna_fit_score NUMERIC,
  ADD COLUMN IF NOT EXISTS voice_fit_score NUMERIC,
  ADD COLUMN IF NOT EXISTS topic_fit_score NUMERIC,
  ADD COLUMN IF NOT EXISTS mood_fit_score NUMERIC,
  ADD COLUMN IF NOT EXISTS uniqueness_score NUMERIC,
  ADD COLUMN IF NOT EXISTS sibling_collision_score NUMERIC,
  ADD COLUMN IF NOT EXISTS genericness_score NUMERIC,
  ADD COLUMN IF NOT EXISTS dna_decision TEXT,
  ADD COLUMN IF NOT EXISTS dna_reasons JSONB;

ALTER TABLE IF EXISTS public.auto_post_queue
  DROP CONSTRAINT IF EXISTS auto_post_queue_dna_decision_check;
ALTER TABLE IF EXISTS public.auto_post_queue
  ADD CONSTRAINT auto_post_queue_dna_decision_check
  CHECK (
    dna_decision IS NULL OR
    dna_decision IN ('pass', 'pass_unscored', 'regenerate', 'needs_review', 'block')
  );

ALTER TABLE IF EXISTS public.posts
  DROP CONSTRAINT IF EXISTS posts_dna_decision_check;
ALTER TABLE IF EXISTS public.posts
  ADD CONSTRAINT posts_dna_decision_check
  CHECK (
    dna_decision IS NULL OR
    dna_decision IN ('pass', 'pass_unscored', 'regenerate', 'needs_review', 'block')
  );

ALTER TABLE IF EXISTS public.auto_post_queue
  DROP CONSTRAINT IF EXISTS auto_post_queue_dna_score_bounds_check;
ALTER TABLE IF EXISTS public.auto_post_queue
  ADD CONSTRAINT auto_post_queue_dna_score_bounds_check
  CHECK (
    (dna_fit_score IS NULL OR dna_fit_score BETWEEN 0 AND 100) AND
    (voice_fit_score IS NULL OR voice_fit_score BETWEEN 0 AND 100) AND
    (topic_fit_score IS NULL OR topic_fit_score BETWEEN 0 AND 100) AND
    (mood_fit_score IS NULL OR mood_fit_score BETWEEN 0 AND 100) AND
    (uniqueness_score IS NULL OR uniqueness_score BETWEEN 0 AND 100) AND
    (sibling_collision_score IS NULL OR sibling_collision_score BETWEEN 0 AND 100) AND
    (genericness_score IS NULL OR genericness_score BETWEEN 0 AND 100)
  );

ALTER TABLE IF EXISTS public.posts
  DROP CONSTRAINT IF EXISTS posts_dna_score_bounds_check;
ALTER TABLE IF EXISTS public.posts
  ADD CONSTRAINT posts_dna_score_bounds_check
  CHECK (
    (dna_fit_score IS NULL OR dna_fit_score BETWEEN 0 AND 100) AND
    (voice_fit_score IS NULL OR voice_fit_score BETWEEN 0 AND 100) AND
    (topic_fit_score IS NULL OR topic_fit_score BETWEEN 0 AND 100) AND
    (mood_fit_score IS NULL OR mood_fit_score BETWEEN 0 AND 100) AND
    (uniqueness_score IS NULL OR uniqueness_score BETWEEN 0 AND 100) AND
    (sibling_collision_score IS NULL OR sibling_collision_score BETWEEN 0 AND 100) AND
    (genericness_score IS NULL OR genericness_score BETWEEN 0 AND 100)
  );

CREATE INDEX IF NOT EXISTS idx_auto_post_queue_dna_scores
  ON public.auto_post_queue(account_id, dna_decision, dna_fit_score, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_posts_dna_scores
  ON public.posts(account_id, dna_decision, dna_fit_score, published_at DESC);

ALTER TABLE IF EXISTS public.account_dna ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.account_dna_examples ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.account_dna_rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.account_uniqueness_metrics ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  IF to_regclass('public.account_dna') IS NOT NULL THEN
    DROP POLICY IF EXISTS "Workspace members can read account DNA" ON public.account_dna;
    IF NOT EXISTS (
      SELECT 1 FROM pg_policies
      WHERE schemaname = 'public'
        AND tablename = 'account_dna'
        AND policyname = 'Workspace members can read account DNA'
    ) THEN
      CREATE POLICY "Workspace members can read account DNA"
        ON public.account_dna
        FOR SELECT
        USING (
          EXISTS (
            SELECT 1
            FROM public.workspace_members wm
            WHERE wm.workspace_id = account_dna.workspace_id
              AND wm.user_id = auth.uid()::text
          )
        );
    END IF;
  END IF;

  IF to_regclass('public.account_dna_examples') IS NOT NULL THEN
    DROP POLICY IF EXISTS "Workspace members can read account DNA examples" ON public.account_dna_examples;
    IF NOT EXISTS (
      SELECT 1 FROM pg_policies
      WHERE schemaname = 'public'
        AND tablename = 'account_dna_examples'
        AND policyname = 'Workspace members can read account DNA examples'
    ) THEN
      CREATE POLICY "Workspace members can read account DNA examples"
        ON public.account_dna_examples
        FOR SELECT
        USING (
          EXISTS (
            SELECT 1
            FROM public.workspace_members wm
            WHERE wm.workspace_id = account_dna_examples.workspace_id
              AND wm.user_id = auth.uid()::text
          )
        );
    END IF;
  END IF;

  IF to_regclass('public.account_dna_rules') IS NOT NULL THEN
    DROP POLICY IF EXISTS "Workspace members can read account DNA rules" ON public.account_dna_rules;
    IF NOT EXISTS (
      SELECT 1 FROM pg_policies
      WHERE schemaname = 'public'
        AND tablename = 'account_dna_rules'
        AND policyname = 'Workspace members can read account DNA rules'
    ) THEN
      CREATE POLICY "Workspace members can read account DNA rules"
        ON public.account_dna_rules
        FOR SELECT
        USING (
          EXISTS (
            SELECT 1
            FROM public.workspace_members wm
            WHERE wm.workspace_id = account_dna_rules.workspace_id
              AND wm.user_id = auth.uid()::text
          )
        );
    END IF;
  END IF;

  IF to_regclass('public.account_uniqueness_metrics') IS NOT NULL THEN
    DROP POLICY IF EXISTS "Workspace members can read uniqueness metrics" ON public.account_uniqueness_metrics;
    IF NOT EXISTS (
      SELECT 1 FROM pg_policies
      WHERE schemaname = 'public'
        AND tablename = 'account_uniqueness_metrics'
        AND policyname = 'Workspace members can read uniqueness metrics'
    ) THEN
      CREATE POLICY "Workspace members can read uniqueness metrics"
        ON public.account_uniqueness_metrics
        FOR SELECT
        USING (
          EXISTS (
            SELECT 1
            FROM public.workspace_members wm
            WHERE wm.workspace_id = account_uniqueness_metrics.workspace_id
              AND wm.user_id = auth.uid()::text
          )
        );
    END IF;
  END IF;
END $$;

COMMIT;

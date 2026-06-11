-- Creator DNA v1: creator-level identity plus account-level flavor.
-- Account DNA remains for compatibility, but creator_dna becomes the identity source.

CREATE TABLE IF NOT EXISTS public.creator_dna (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

  workspace_id TEXT NOT NULL,
  group_id TEXT NOT NULL,

  version INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL DEFAULT 'draft',
  confidence NUMERIC NOT NULL DEFAULT 0,

  creator_key TEXT NOT NULL,
  creator_name TEXT NOT NULL,
  archetype TEXT NOT NULL,
  follower_promise TEXT NOT NULL,
  identity_summary TEXT NOT NULL,

  core_topics JSONB NOT NULL DEFAULT '[]'::jsonb,
  core_motifs JSONB NOT NULL DEFAULT '[]'::jsonb,
  signature_beliefs JSONB NOT NULL DEFAULT '[]'::jsonb,
  shared_voice_traits JSONB NOT NULL DEFAULT '[]'::jsonb,
  allowed_moods JSONB NOT NULL DEFAULT '[]'::jsonb,
  shared_phrase_bank JSONB NOT NULL DEFAULT '[]'::jsonb,
  taboo_topics JSONB NOT NULL DEFAULT '[]'::jsonb,

  source_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
  generated_from TEXT NOT NULL DEFAULT 'account_dna_backfill',

  last_scored_at TIMESTAMPTZ,
  last_refreshed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT creator_dna_status_check
    CHECK (status IN ('draft', 'active', 'retired'))
);

CREATE UNIQUE INDEX IF NOT EXISTS creator_dna_one_active_per_group
  ON public.creator_dna(workspace_id, group_id)
  WHERE status = 'active';

CREATE INDEX IF NOT EXISTS creator_dna_workspace_group_idx
  ON public.creator_dna(workspace_id, group_id, status, version DESC);

CREATE TABLE IF NOT EXISTS public.account_flavor (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

  workspace_id TEXT NOT NULL,
  group_id TEXT NOT NULL,
  account_id TEXT NOT NULL,
  creator_dna_id UUID NOT NULL REFERENCES public.creator_dna(id) ON DELETE CASCADE,

  status TEXT NOT NULL DEFAULT 'draft',
  flavor_name TEXT NOT NULL DEFAULT 'balanced',

  topic_emphasis JSONB NOT NULL DEFAULT '[]'::jsonb,
  motif_emphasis JSONB NOT NULL DEFAULT '[]'::jsonb,
  format_emphasis JSONB NOT NULL DEFAULT '[]'::jsonb,
  archetype_bias JSONB NOT NULL DEFAULT '[]'::jsonb,
  phrase_cooldowns JSONB NOT NULL DEFAULT '[]'::jsonb,
  flavor_notes TEXT,

  source_account_dna_id UUID REFERENCES public.account_dna(id) ON DELETE SET NULL,
  source_summary JSONB NOT NULL DEFAULT '{}'::jsonb,

  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT account_flavor_status_check
    CHECK (status IN ('draft', 'active', 'retired'))
);

CREATE UNIQUE INDEX IF NOT EXISTS account_flavor_one_active_per_account
  ON public.account_flavor(account_id)
  WHERE status = 'active';

CREATE INDEX IF NOT EXISTS account_flavor_creator_idx
  ON public.account_flavor(creator_dna_id, account_id, status);

CREATE INDEX IF NOT EXISTS account_flavor_workspace_group_idx
  ON public.account_flavor(workspace_id, group_id, account_id);

ALTER TABLE public.account_dna
  ADD COLUMN IF NOT EXISTS creator_dna_id UUID REFERENCES public.creator_dna(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS account_flavor_id UUID REFERENCES public.account_flavor(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS account_dna_creator_dna_idx
  ON public.account_dna(creator_dna_id)
  WHERE creator_dna_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.creator_identity_shape_usage (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

  workspace_id TEXT NOT NULL,
  group_id TEXT NOT NULL,
  creator_dna_id UUID REFERENCES public.creator_dna(id) ON DELETE SET NULL,
  account_id TEXT,

  source_table TEXT NOT NULL,
  source_id TEXT,
  content TEXT NOT NULL,
  normalized_content_hash TEXT,
  shape_id TEXT,

  used_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT creator_identity_shape_source_check
    CHECK (source_table IN ('auto_post_queue', 'posts', 'manual'))
);

CREATE INDEX IF NOT EXISTS creator_identity_shape_recent_idx
  ON public.creator_identity_shape_usage(workspace_id, group_id, used_at DESC);

CREATE INDEX IF NOT EXISTS creator_identity_shape_id_recent_idx
  ON public.creator_identity_shape_usage(workspace_id, group_id, shape_id, used_at DESC)
  WHERE shape_id IS NOT NULL;

ALTER TABLE public.creator_dna ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.account_flavor ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.creator_identity_shape_usage ENABLE ROW LEVEL SECURITY;

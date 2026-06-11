-- Campaign-aware scheduling manager v1.
-- ThreadsDashboard becomes the scheduling/QStash owner for Campaign Factory
-- drafts. Campaign metadata is also mirrored into first-class columns so
-- duplicate prevention and operations reporting are database-enforced.

ALTER TABLE IF EXISTS public.posts
  ADD COLUMN IF NOT EXISTS campaign_factory_asset_id TEXT,
  ADD COLUMN IF NOT EXISTS campaign_factory_distribution_plan_id TEXT,
  ADD COLUMN IF NOT EXISTS campaign_factory_post_key TEXT,
  ADD COLUMN IF NOT EXISTS campaign_factory_content_fingerprint TEXT,
  ADD COLUMN IF NOT EXISTS campaign_factory_caption_hash TEXT,
  ADD COLUMN IF NOT EXISTS campaign_factory_concept_id TEXT,
  ADD COLUMN IF NOT EXISTS campaign_factory_variant_family_id TEXT,
  ADD COLUMN IF NOT EXISTS campaign_factory_variant_id TEXT,
  ADD COLUMN IF NOT EXISTS campaign_factory_parent_asset_id TEXT,
  ADD COLUMN IF NOT EXISTS qstash_message_id TEXT,
  ADD COLUMN IF NOT EXISTS qstash_dispatched_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS qstash_dispatch_status TEXT,
  ADD COLUMN IF NOT EXISTS qstash_failure_reason TEXT,
  ADD COLUMN IF NOT EXISTS platform_draft_validated BOOLEAN NOT NULL DEFAULT FALSE;

UPDATE public.posts
SET
  campaign_factory_asset_id = COALESCE(campaign_factory_asset_id, metadata #>> '{campaign_factory,asset_id}', metadata #>> '{campaign_factory,rendered_asset_id}'),
  campaign_factory_distribution_plan_id = COALESCE(campaign_factory_distribution_plan_id, metadata #>> '{campaign_factory,distribution_plan_id}'),
  campaign_factory_post_key = COALESCE(campaign_factory_post_key, metadata #>> '{campaign_factory,post_key}'),
  campaign_factory_content_fingerprint = COALESCE(campaign_factory_content_fingerprint, metadata #>> '{campaign_factory,content_fingerprint}', metadata #>> '{campaign_factory,content_hash}'),
  campaign_factory_caption_hash = COALESCE(campaign_factory_caption_hash, metadata #>> '{campaign_factory,caption_hash}'),
  campaign_factory_concept_id = COALESCE(campaign_factory_concept_id, metadata->'campaign_factory'->>'concept_id', metadata #>> '{campaign_factory,handoff_manifest,concept_id}'),
  campaign_factory_variant_family_id = COALESCE(campaign_factory_variant_family_id, metadata->'campaign_factory'->>'variant_family_id', metadata #>> '{campaign_factory,handoff_manifest,variant_family_id}'),
  campaign_factory_variant_id = COALESCE(campaign_factory_variant_id, metadata->'campaign_factory'->>'variant_id', metadata #>> '{campaign_factory,handoff_manifest,variant_id}'),
  campaign_factory_parent_asset_id = COALESCE(campaign_factory_parent_asset_id, metadata->'campaign_factory'->>'parent_asset_id', metadata #>> '{campaign_factory,handoff_manifest,parent_asset_id}'),
  qstash_message_id = COALESCE(qstash_message_id, metadata #>> '{qstash_message_id}'),
  qstash_dispatch_status = COALESCE(qstash_dispatch_status, CASE WHEN metadata #>> '{qstash_message_id}' IS NOT NULL THEN 'dispatched' ELSE NULL END),
  platform_draft_validated = CASE
    WHEN platform_draft_validated THEN TRUE
    WHEN metadata #>> '{campaign_factory,platform_state}' = 'platform_draft_validated' THEN TRUE
    WHEN metadata #>> '{campaign_factory,asset_state}' IN ('publishable_candidate', 'exportable') AND metadata #> '{campaign_factory,handoff_manifest}' IS NOT NULL THEN TRUE
    ELSE FALSE
  END
WHERE metadata ? 'campaign_factory'
   OR metadata ? 'qstash_message_id';

CREATE UNIQUE INDEX IF NOT EXISTS posts_campaign_distribution_plan_active_uniq
  ON public.posts(user_id, campaign_factory_distribution_plan_id)
  WHERE campaign_factory_distribution_plan_id IS NOT NULL
    AND status IN ('draft', 'scheduled', 'publishing', 'published');

CREATE UNIQUE INDEX IF NOT EXISTS posts_campaign_asset_account_time_active_uniq
  ON public.posts(user_id, instagram_account_id, campaign_factory_asset_id, scheduled_for)
  WHERE instagram_account_id IS NOT NULL
    AND campaign_factory_asset_id IS NOT NULL
    AND scheduled_for IS NOT NULL
    AND status IN ('scheduled', 'publishing', 'published');

CREATE INDEX IF NOT EXISTS posts_campaign_schedule_ops_idx
  ON public.posts(user_id, platform, status, scheduled_for)
  WHERE platform = 'instagram'
    AND campaign_factory_asset_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS posts_campaign_qstash_idx
  ON public.posts(user_id, qstash_dispatch_status, scheduled_for)
  WHERE campaign_factory_asset_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_posts_campaign_variant_family_account
  ON public.posts(user_id, instagram_account_id, campaign_factory_variant_family_id, scheduled_for)
  WHERE campaign_factory_variant_family_id IS NOT NULL
    AND status IN ('draft', 'scheduled', 'publishing', 'published');

CREATE INDEX IF NOT EXISTS idx_posts_campaign_variant_account
  ON public.posts(user_id, instagram_account_id, campaign_factory_variant_id)
  WHERE campaign_factory_variant_id IS NOT NULL
    AND status IN ('draft', 'scheduled', 'publishing', 'published');

CREATE TABLE IF NOT EXISTS public.campaign_schedule_batches (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'planned' CHECK (
    status IN ('planned', 'dry_run', 'committing', 'committed', 'partial', 'failed')
  ),
  dry_run BOOLEAN NOT NULL DEFAULT TRUE,
  requested_count INTEGER NOT NULL DEFAULT 0,
  scheduled_count INTEGER NOT NULL DEFAULT 0,
  failed_count INTEGER NOT NULL DEFAULT 0,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.campaign_schedule_batch_items (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  batch_id UUID NOT NULL REFERENCES public.campaign_schedule_batches(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  post_id TEXT REFERENCES public.posts(id) ON DELETE SET NULL,
  campaign_factory_asset_id TEXT,
  campaign_factory_distribution_plan_id TEXT,
  instagram_account_id TEXT,
  scheduled_for TIMESTAMPTZ,
  status TEXT NOT NULL DEFAULT 'planned' CHECK (
    status IN ('planned', 'validated', 'scheduled', 'failed', 'skipped')
  ),
  qstash_message_id TEXT,
  failure_reason TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS campaign_schedule_batches_user_created_idx
  ON public.campaign_schedule_batches(user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS campaign_schedule_batch_items_batch_idx
  ON public.campaign_schedule_batch_items(batch_id, status);

CREATE INDEX IF NOT EXISTS campaign_schedule_batch_items_post_idx
  ON public.campaign_schedule_batch_items(post_id)
  WHERE post_id IS NOT NULL;

ALTER TABLE IF EXISTS public.campaign_schedule_batches ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.campaign_schedule_batch_items ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  IF to_regclass('public.campaign_schedule_batches') IS NOT NULL THEN
    DROP POLICY IF EXISTS "campaign_schedule_batches_owner_select" ON public.campaign_schedule_batches;
    CREATE POLICY "campaign_schedule_batches_owner_select"
      ON public.campaign_schedule_batches
      FOR SELECT
      TO authenticated
      USING ((select auth.uid())::text = user_id);

    DROP POLICY IF EXISTS "campaign_schedule_batches_owner_insert" ON public.campaign_schedule_batches;
    CREATE POLICY "campaign_schedule_batches_owner_insert"
      ON public.campaign_schedule_batches
      FOR INSERT
      TO authenticated
      WITH CHECK ((select auth.uid())::text = user_id);

    DROP POLICY IF EXISTS "campaign_schedule_batches_owner_update" ON public.campaign_schedule_batches;
    CREATE POLICY "campaign_schedule_batches_owner_update"
      ON public.campaign_schedule_batches
      FOR UPDATE
      TO authenticated
      USING ((select auth.uid())::text = user_id)
      WITH CHECK ((select auth.uid())::text = user_id);
  END IF;

  IF to_regclass('public.campaign_schedule_batch_items') IS NOT NULL THEN
    DROP POLICY IF EXISTS "campaign_schedule_batch_items_owner_select" ON public.campaign_schedule_batch_items;
    CREATE POLICY "campaign_schedule_batch_items_owner_select"
      ON public.campaign_schedule_batch_items
      FOR SELECT
      TO authenticated
      USING ((select auth.uid())::text = user_id);

    DROP POLICY IF EXISTS "campaign_schedule_batch_items_owner_insert" ON public.campaign_schedule_batch_items;
    CREATE POLICY "campaign_schedule_batch_items_owner_insert"
      ON public.campaign_schedule_batch_items
      FOR INSERT
      TO authenticated
      WITH CHECK ((select auth.uid())::text = user_id);

    DROP POLICY IF EXISTS "campaign_schedule_batch_items_owner_update" ON public.campaign_schedule_batch_items;
    CREATE POLICY "campaign_schedule_batch_items_owner_update"
      ON public.campaign_schedule_batch_items
      FOR UPDATE
      TO authenticated
      USING ((select auth.uid())::text = user_id)
      WITH CHECK ((select auth.uid())::text = user_id);
  END IF;
END $$;

GRANT SELECT, INSERT, UPDATE ON public.campaign_schedule_batches TO authenticated;
GRANT SELECT, INSERT, UPDATE ON public.campaign_schedule_batch_items TO authenticated;
GRANT ALL ON public.campaign_schedule_batches TO service_role;
GRANT ALL ON public.campaign_schedule_batch_items TO service_role;

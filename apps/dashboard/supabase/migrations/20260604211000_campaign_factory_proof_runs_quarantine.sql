-- Durable audit trail for Campaign Factory proof attempts and quarantined assets.

CREATE TABLE IF NOT EXISTS public.proof_runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  asset_id TEXT NOT NULL,
  distribution_plan_id TEXT,
  threadsdash_draft_id TEXT REFERENCES public.posts(id) ON DELETE SET NULL,
  threadsdash_post_id TEXT REFERENCES public.posts(id) ON DELETE SET NULL,
  status TEXT NOT NULL DEFAULT 'started' CHECK (
    status IN (
      'started',
      'publishable_candidate',
      'exported',
      'platform_draft_validated',
      'published',
      'metrics_eligible',
      'failed',
      'quarantined',
      'retired'
    )
  ),
  failed_stage TEXT,
  blocking_reason TEXT,
  root_cause TEXT,
  metrics_eligible BOOLEAN NOT NULL DEFAULT FALSE,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ,
  metrics_imported_at TIMESTAMPTZ,
  caption_report_generated_at TIMESTAMPTZ,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS proof_runs_user_asset_idx
  ON public.proof_runs(user_id, asset_id, started_at DESC);

CREATE INDEX IF NOT EXISTS proof_runs_user_status_idx
  ON public.proof_runs(user_id, status, started_at DESC);

CREATE INDEX IF NOT EXISTS proof_runs_distribution_plan_idx
  ON public.proof_runs(distribution_plan_id)
  WHERE distribution_plan_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.quarantined_assets (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  asset_id TEXT NOT NULL,
  reason TEXT NOT NULL,
  root_cause TEXT,
  blocked_stage TEXT,
  can_retry BOOLEAN NOT NULL DEFAULT FALSE,
  retry_requires_new_render BOOLEAN NOT NULL DEFAULT TRUE,
  excluded_from_metrics BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE(user_id, asset_id)
);

CREATE INDEX IF NOT EXISTS quarantined_assets_user_created_idx
  ON public.quarantined_assets(user_id, created_at DESC);

ALTER TABLE IF EXISTS public.proof_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.quarantined_assets ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  IF to_regclass('public.proof_runs') IS NOT NULL THEN
    IF NOT EXISTS (
      SELECT 1 FROM pg_policies
      WHERE schemaname = 'public'
        AND tablename = 'proof_runs'
        AND policyname = 'Users read own proof runs'
    ) THEN
      EXECUTE $policy$
        CREATE POLICY "Users read own proof runs"
          ON public.proof_runs FOR SELECT
          USING (auth.uid()::text = user_id)
      $policy$;
    END IF;

    IF NOT EXISTS (
      SELECT 1 FROM pg_policies
      WHERE schemaname = 'public'
        AND tablename = 'proof_runs'
        AND policyname = 'Users insert own proof runs'
    ) THEN
      EXECUTE $policy$
        CREATE POLICY "Users insert own proof runs"
          ON public.proof_runs FOR INSERT
          WITH CHECK (auth.uid()::text = user_id)
      $policy$;
    END IF;

    IF NOT EXISTS (
      SELECT 1 FROM pg_policies
      WHERE schemaname = 'public'
        AND tablename = 'proof_runs'
        AND policyname = 'Users update own proof runs'
    ) THEN
      EXECUTE $policy$
        CREATE POLICY "Users update own proof runs"
          ON public.proof_runs FOR UPDATE
          USING (auth.uid()::text = user_id)
          WITH CHECK (auth.uid()::text = user_id)
      $policy$;
    END IF;
  END IF;

  IF to_regclass('public.quarantined_assets') IS NOT NULL THEN
    IF NOT EXISTS (
      SELECT 1 FROM pg_policies
      WHERE schemaname = 'public'
        AND tablename = 'quarantined_assets'
        AND policyname = 'Users read own quarantined assets'
    ) THEN
      EXECUTE $policy$
        CREATE POLICY "Users read own quarantined assets"
          ON public.quarantined_assets FOR SELECT
          USING (auth.uid()::text = user_id)
      $policy$;
    END IF;

    IF NOT EXISTS (
      SELECT 1 FROM pg_policies
      WHERE schemaname = 'public'
        AND tablename = 'quarantined_assets'
        AND policyname = 'Users insert own quarantined assets'
    ) THEN
      EXECUTE $policy$
        CREATE POLICY "Users insert own quarantined assets"
          ON public.quarantined_assets FOR INSERT
          WITH CHECK (auth.uid()::text = user_id)
      $policy$;
    END IF;

    IF NOT EXISTS (
      SELECT 1 FROM pg_policies
      WHERE schemaname = 'public'
        AND tablename = 'quarantined_assets'
        AND policyname = 'Users update own quarantined assets'
    ) THEN
      EXECUTE $policy$
        CREATE POLICY "Users update own quarantined assets"
          ON public.quarantined_assets FOR UPDATE
          USING (auth.uid()::text = user_id)
          WITH CHECK (auth.uid()::text = user_id)
      $policy$;
    END IF;
  END IF;
END $$;

GRANT ALL ON public.proof_runs TO service_role;
GRANT ALL ON public.quarantined_assets TO service_role;

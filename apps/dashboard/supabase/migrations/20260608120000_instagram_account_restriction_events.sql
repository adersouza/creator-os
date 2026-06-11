CREATE TABLE IF NOT EXISTS public.instagram_account_restriction_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id TEXT NOT NULL,
  instagram_account_id UUID NOT NULL REFERENCES public.instagram_accounts(id) ON DELETE CASCADE,
  restriction_type TEXT NOT NULL CHECK (
    restriction_type IN (
      'link_sharing_restricted',
      'recommendation_limited',
      'not_recommended',
      'manual_review_required',
      'publish_blocked'
    )
  ),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'resolved', 'expired')),
  severity TEXT NOT NULL DEFAULT 'blocking' CHECK (severity IN ('info', 'warning', 'blocking')),
  recommendation_eligibility_state TEXT NOT NULL DEFAULT 'unknown' CHECK (
    recommendation_eligibility_state IN (
      'eligible',
      'unknown',
      'limited',
      'not_recommended',
      'manual_review_required'
    )
  ),
  review_required BOOLEAN NOT NULL DEFAULT false,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  ends_at TIMESTAMPTZ,
  resolved_at TIMESTAMPTZ,
  source TEXT NOT NULL DEFAULT 'operator',
  source_confidence TEXT NOT NULL DEFAULT 'medium' CHECK (source_confidence IN ('low', 'medium', 'high')),
  notes TEXT,
  evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_by TEXT,
  updated_by TEXT,
  resolved_by TEXT,
  resolved_reason TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT instagram_account_restriction_events_resolved_reason_check
    CHECK (status != 'resolved' OR (resolved_at IS NOT NULL AND nullif(trim(coalesce(resolved_reason, '')), '') IS NOT NULL))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_ig_account_restriction_active_unique
  ON public.instagram_account_restriction_events(instagram_account_id, restriction_type)
  WHERE status = 'active' AND resolved_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_ig_account_restrictions_user_active
  ON public.instagram_account_restriction_events(user_id, status, instagram_account_id);

CREATE INDEX IF NOT EXISTS idx_ig_account_restrictions_expiry
  ON public.instagram_account_restriction_events(user_id, ends_at)
  WHERE status IN ('active', 'expired');

ALTER TABLE IF EXISTS public.instagram_account_restriction_events ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users view own instagram account restriction events" ON public.instagram_account_restriction_events;
DO $$
BEGIN
  IF to_regclass('public.instagram_account_restriction_events') IS NOT NULL
    AND NOT EXISTS (
      SELECT 1
      FROM pg_policies
      WHERE schemaname = 'public'
        AND tablename = 'instagram_account_restriction_events'
        AND policyname = 'Users view own instagram account restriction events'
    )
  THEN
    CREATE POLICY "Users view own instagram account restriction events"
      ON public.instagram_account_restriction_events
      FOR SELECT
      TO authenticated
      USING (user_id = (select auth.uid())::text);
  END IF;
END $$;

DROP POLICY IF EXISTS "Service role manages instagram account restriction events" ON public.instagram_account_restriction_events;
DO $$
BEGIN
  IF to_regclass('public.instagram_account_restriction_events') IS NOT NULL
    AND NOT EXISTS (
      SELECT 1
      FROM pg_policies
      WHERE schemaname = 'public'
        AND tablename = 'instagram_account_restriction_events'
        AND policyname = 'Service role manages instagram account restriction events'
    )
  THEN
    CREATE POLICY "Service role manages instagram account restriction events"
      ON public.instagram_account_restriction_events
      FOR ALL
      TO service_role
      USING (true)
      WITH CHECK (true);
  END IF;
END $$;

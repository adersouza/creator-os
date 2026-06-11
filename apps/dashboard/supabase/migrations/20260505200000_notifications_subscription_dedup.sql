-- ============================================================================
-- Stripe webhook notification dedup
-- ============================================================================
-- Date: 2026-05-05
-- The Stripe webhook handler's stale-lock recovery path (api/webhook.ts:170)
-- can re-claim a previously-processing event after 5min TTL and re-run the
-- whole switch. trial_will_end inserts a `notifications` row each run, so
-- a stale-lock retry would double-insert. Add a partial unique index on
-- (user_id, type, data->>'subscription_id') so retries are idempotent.
-- ============================================================================

DO $$
BEGIN
  IF to_regclass('public.notifications') IS NOT NULL THEN
    EXECUTE $index$
      CREATE UNIQUE INDEX IF NOT EXISTS uniq_notifications_user_type_sub
        ON public.notifications (user_id, type, ((data->>'subscription_id')))
        WHERE data ? 'subscription_id'
    $index$;
  END IF;
END $$;

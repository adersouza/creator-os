-- ============================================================================
-- OAuth scope drift detection
-- ============================================================================
-- Long-lived Meta tokens retain the scopes granted when they were issued.
-- Track tokens that refresh successfully but are missing current required scopes.
-- ============================================================================

ALTER TABLE IF EXISTS public.accounts
  ADD COLUMN IF NOT EXISTS scope_drift_detected_at TIMESTAMPTZ;

ALTER TABLE IF EXISTS public.instagram_accounts
  ADD COLUMN IF NOT EXISTS scope_drift_detected_at TIMESTAMPTZ;

DO $$
BEGIN
  IF to_regclass('public.notifications') IS NOT NULL THEN
    EXECUTE $index$
      CREATE UNIQUE INDEX IF NOT EXISTS uniq_notifications_user_type_account_scope_drift
        ON public.notifications (user_id, type, ((data->>'account_id')))
        WHERE type = 'scope_drift' AND data ? 'account_id'
    $index$;
  END IF;
END $$;

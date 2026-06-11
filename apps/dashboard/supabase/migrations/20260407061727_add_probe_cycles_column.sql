-- Reconstructed from schema_migrations on prod (remote-only).
-- version: 20260407061727
-- applied-by: add_probe_cycles_column migration row


DO $$
BEGIN
  IF to_regclass('public.account_autoposter_state') IS NOT NULL THEN
    ALTER TABLE public.account_autoposter_state
      ADD COLUMN IF NOT EXISTS probe_cycles_completed INTEGER NOT NULL DEFAULT 0;

    COMMENT ON COLUMN public.account_autoposter_state.probe_cycles_completed IS 'Completed suppression probe cycles. After 2 failed cycles -> permanently suppressed, requires manual override.';
  END IF;
END $$;

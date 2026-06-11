-- Reconstructed from schema_migrations on prod (remote-only).
-- version: 20260407054531
-- applied-by: add_flop_tracking_columns migration row


-- Add flop tracking columns to break the infinite flop_delay loop.
-- The evaluator now tracks WHICH post triggered the flop so it doesn't
-- re-extend the delay for the same post every 15 minutes.
DO $$
BEGIN
  IF to_regclass('public.account_autoposter_state') IS NOT NULL THEN
    ALTER TABLE public.account_autoposter_state
      ADD COLUMN IF NOT EXISTS last_flop_post_id TEXT,
      ADD COLUMN IF NOT EXISTS flop_triggered_at TIMESTAMPTZ;

    COMMENT ON COLUMN public.account_autoposter_state.last_flop_post_id IS 'Post ID that triggered the current flop_delay - prevents re-extending for same post';
    COMMENT ON COLUMN public.account_autoposter_state.flop_triggered_at IS 'When the current flop_delay was first triggered - enables max duration cap (8h)';
  END IF;
END $$;

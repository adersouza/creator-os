DO $$
BEGIN
  IF to_regclass('public.account_autoposter_state') IS NOT NULL THEN
    ALTER TABLE public.account_autoposter_state
      ADD COLUMN IF NOT EXISTS should_retire BOOLEAN DEFAULT false;
  END IF;
END $$;

-- Bring production schema back in line with the cohort pipeline code path.
-- A historical local migration added these fields, but production migration
-- history skipped that version. Keep this current migration clean-replay safe.

BEGIN;

ALTER TABLE IF EXISTS public.accounts
  ADD COLUMN IF NOT EXISTS user_niche text,
  ADD COLUMN IF NOT EXISTS inferred_niche text;

ALTER TABLE IF EXISTS public.instagram_accounts
  ADD COLUMN IF NOT EXISTS user_niche text,
  ADD COLUMN IF NOT EXISTS inferred_niche text;

CREATE INDEX IF NOT EXISTS idx_accounts_cohort_niche
  ON public.accounts (COALESCE(user_niche, inferred_niche))
  WHERE user_niche IS NOT NULL OR inferred_niche IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_instagram_accounts_cohort_niche
  ON public.instagram_accounts (COALESCE(user_niche, inferred_niche))
  WHERE user_niche IS NOT NULL OR inferred_niche IS NOT NULL;

COMMIT;

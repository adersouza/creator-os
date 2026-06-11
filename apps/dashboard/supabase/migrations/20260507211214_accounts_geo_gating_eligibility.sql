-- Store Threads geo-gating eligibility from the Threads API.
-- Existing environments may not have this column yet; the app also falls back
-- when reading against older schemas.
ALTER TABLE public.accounts
  ADD COLUMN IF NOT EXISTS is_eligible_for_geo_gating boolean NOT NULL DEFAULT false;

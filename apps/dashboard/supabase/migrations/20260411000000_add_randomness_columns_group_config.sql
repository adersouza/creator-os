-- Add human-randomness scheduling columns to auto_post_group_config.
-- These were read in accountPlanner.ts (commit 52601c5b) but never landed in schema.
--
-- rest_days_per_week:            0 = no rest days (matches code ?? 0 fallback)
-- min_posts_per_account_per_day: nullable — code falls back to posts_per_account_per_day when null

ALTER TABLE public.auto_post_group_config
  ADD COLUMN IF NOT EXISTS rest_days_per_week INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS min_posts_per_account_per_day INTEGER DEFAULT NULL;

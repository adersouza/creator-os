-- Config drift fix: crossreshare columns + NOT NULL enforcement
--
-- crossreshare_to_ig / crossreshare_to_ig_dark_mode may already exist in
-- production (added via direct SQL) but are missing from migration history.
-- This migration adds them if absent and tightens nullable columns that
-- code treats as non-nullable (all currently have zero NULLs in prod).

-- Step 1: Add columns if missing (idempotent for fresh environments)
ALTER TABLE public.auto_post_group_config
  ADD COLUMN IF NOT EXISTS crossreshare_to_ig BOOLEAN DEFAULT false,
  ADD COLUMN IF NOT EXISTS crossreshare_to_ig_dark_mode BOOLEAN DEFAULT false;

-- Step 2: Backfill any NULLs in columns that code defaults assume non-null
UPDATE public.auto_post_group_config SET crossreshare_to_ig = false WHERE crossreshare_to_ig IS NULL;
UPDATE public.auto_post_group_config SET crossreshare_to_ig_dark_mode = false WHERE crossreshare_to_ig_dark_mode IS NULL;
UPDATE public.auto_post_group_config SET enable_human_noise = true WHERE enable_human_noise IS NULL;
UPDATE public.auto_post_group_config SET round_robin_enabled = true WHERE round_robin_enabled IS NULL;
UPDATE public.auto_post_group_config SET media_attachment_chance = 0 WHERE media_attachment_chance IS NULL;
UPDATE public.auto_post_group_config SET media_source = 'global' WHERE media_source IS NULL;
UPDATE public.auto_post_group_config SET require_approval = false WHERE require_approval IS NULL;

-- Step 3: Tighten to NOT NULL now that all rows are backfilled
ALTER TABLE public.auto_post_group_config
  ALTER COLUMN crossreshare_to_ig SET NOT NULL,
  ALTER COLUMN crossreshare_to_ig_dark_mode SET NOT NULL,
  ALTER COLUMN enable_human_noise SET NOT NULL,
  ALTER COLUMN round_robin_enabled SET NOT NULL,
  ALTER COLUMN media_attachment_chance SET NOT NULL,
  ALTER COLUMN media_source SET NOT NULL,
  ALTER COLUMN require_approval SET NOT NULL;

-- Reconstructed from schema_migrations on prod (remote-only).
-- version: 20260403212014
-- applied-by: add_crossreshare_columns_enforce_not_null migration row

-- Config drift fix: crossreshare columns + NOT NULL enforcement
ALTER TABLE public.auto_post_group_config
  ADD COLUMN IF NOT EXISTS crossreshare_to_ig BOOLEAN DEFAULT false,
  ADD COLUMN IF NOT EXISTS crossreshare_to_ig_dark_mode BOOLEAN DEFAULT false;

UPDATE public.auto_post_group_config SET crossreshare_to_ig = false WHERE crossreshare_to_ig IS NULL;
UPDATE public.auto_post_group_config SET crossreshare_to_ig_dark_mode = false WHERE crossreshare_to_ig_dark_mode IS NULL;
UPDATE public.auto_post_group_config SET enable_human_noise = true WHERE enable_human_noise IS NULL;
UPDATE public.auto_post_group_config SET round_robin_enabled = true WHERE round_robin_enabled IS NULL;
UPDATE public.auto_post_group_config SET media_attachment_chance = 0 WHERE media_attachment_chance IS NULL;
UPDATE public.auto_post_group_config SET media_source = 'global' WHERE media_source IS NULL;
UPDATE public.auto_post_group_config SET require_approval = false WHERE require_approval IS NULL;

ALTER TABLE public.auto_post_group_config
  ALTER COLUMN crossreshare_to_ig SET NOT NULL,
  ALTER COLUMN crossreshare_to_ig_dark_mode SET NOT NULL,
  ALTER COLUMN enable_human_noise SET NOT NULL,
  ALTER COLUMN round_robin_enabled SET NOT NULL,
  ALTER COLUMN media_attachment_chance SET NOT NULL,
  ALTER COLUMN media_source SET NOT NULL,
  ALTER COLUMN require_approval SET NOT NULL;

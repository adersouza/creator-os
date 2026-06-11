-- enable_human_noise is no longer used anywhere in the app layer.
-- Drop the column so config/schema matches the live publishing behavior.

ALTER TABLE public.auto_post_group_config
  DROP COLUMN IF EXISTS enable_human_noise;

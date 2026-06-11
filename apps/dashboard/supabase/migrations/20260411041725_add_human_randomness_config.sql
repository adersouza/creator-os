-- Reconstructed from schema_migrations on prod (remote-only).
-- version: 20260411041725
-- applied-by: add_human_randomness_config migration row


ALTER TABLE auto_post_group_config
ADD COLUMN IF NOT EXISTS min_posts_per_account_per_day integer DEFAULT NULL,
ADD COLUMN IF NOT EXISTS rest_days_per_week integer DEFAULT 0;

COMMENT ON COLUMN auto_post_group_config.min_posts_per_account_per_day IS 'Minimum posts per account per day. When set, daily count is randomized between this and posts_per_account_per_day. NULL = use posts_per_account_per_day (no randomization).';
COMMENT ON COLUMN auto_post_group_config.rest_days_per_week IS 'Number of random rest days per week per account (0-6). Each account gets different rest days, re-rolled weekly.';

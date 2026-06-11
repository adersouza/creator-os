-- Migration: Add last_cron_run_at to auto_post_state and auto_post_group_state
-- Used as a lightweight lock to prevent overlapping cron runs from double-posting

ALTER TABLE public.auto_post_state
ADD COLUMN IF NOT EXISTS last_cron_run_at TIMESTAMPTZ;

ALTER TABLE public.auto_post_group_state
ADD COLUMN IF NOT EXISTS last_cron_run_at TIMESTAMPTZ;

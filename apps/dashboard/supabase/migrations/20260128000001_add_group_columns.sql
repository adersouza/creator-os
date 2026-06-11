-- Migration: Add group_id to existing auto-poster tables
-- Enables per-group content queues and activity tracking

-- Add group_id to auto_post_queue for per-group content pools
ALTER TABLE public.auto_post_queue
ADD COLUMN IF NOT EXISTS group_id TEXT REFERENCES account_groups(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_auto_post_queue_group_id
ON public.auto_post_queue(group_id);

-- Add group_id and group_name to auto_post_activity for per-group logging
ALTER TABLE public.auto_post_activity
ADD COLUMN IF NOT EXISTS group_id TEXT REFERENCES account_groups(id) ON DELETE SET NULL;

ALTER TABLE public.auto_post_activity
ADD COLUMN IF NOT EXISTS group_name TEXT;

CREATE INDEX IF NOT EXISTS idx_auto_post_activity_group_id
ON public.auto_post_activity(group_id);

-- Add group_mode_enabled toggle to auto_post_config
ALTER TABLE public.auto_post_config
ADD COLUMN IF NOT EXISTS group_mode_enabled BOOLEAN NOT NULL DEFAULT false;

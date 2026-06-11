-- Autoposter Audit Fix M2: Add missing columns to auto_post_group_config
-- These fields were accepted by the MCP tool but silently dropped because
-- the columns didn't exist. Now they write through correctly.

ALTER TABLE public.auto_post_group_config
  ADD COLUMN IF NOT EXISTS content_sources JSONB,
  ADD COLUMN IF NOT EXISTS platform TEXT DEFAULT 'threads',
  ADD COLUMN IF NOT EXISTS round_robin_enabled BOOLEAN DEFAULT true,
  ADD COLUMN IF NOT EXISTS media_attachment_chance INTEGER DEFAULT 0,
  ADD COLUMN IF NOT EXISTS media_source TEXT DEFAULT 'global',
  ADD COLUMN IF NOT EXISTS require_approval BOOLEAN DEFAULT false;

-- Migration: Add platform column to auto_post_queue
-- Date: 2026-01-30
-- Purpose: Allow queue items to be tagged for specific platforms (threads/instagram)

ALTER TABLE auto_post_queue ADD COLUMN IF NOT EXISTS platform TEXT NOT NULL DEFAULT 'threads'
  CHECK (platform IN ('threads', 'instagram'));

CREATE INDEX IF NOT EXISTS idx_auto_post_queue_platform ON auto_post_queue(platform);

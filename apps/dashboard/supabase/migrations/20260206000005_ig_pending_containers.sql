-- Migration: IG Pending Containers — Async Instagram container polling
-- Date: 2026-02-06
-- Purpose: Track Instagram media containers for async publish flow
-- instead of blocking inside the Vercel function for up to 5 minutes

CREATE TABLE IF NOT EXISTS ig_pending_containers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  post_id TEXT REFERENCES posts(id) ON DELETE CASCADE,
  container_id TEXT NOT NULL,
  account_id UUID NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',  -- 'pending' | 'ready' | 'error' | 'published'
  created_at TIMESTAMPTZ DEFAULT NOW(),
  last_checked_at TIMESTAMPTZ,
  check_count INT DEFAULT 0,
  error TEXT,
  login_type TEXT DEFAULT 'facebook'  -- 'facebook' | 'instagram'
);

-- Index for the cron to efficiently query pending containers
CREATE INDEX IF NOT EXISTS idx_pending_containers_status
  ON ig_pending_containers(status)
  WHERE status = 'pending';

-- ============================================================================
-- Permissions
-- ============================================================================

ALTER TABLE ig_pending_containers DISABLE ROW LEVEL SECURITY;
GRANT ALL ON ig_pending_containers TO service_role;

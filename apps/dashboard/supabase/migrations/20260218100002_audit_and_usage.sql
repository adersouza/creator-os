-- ============================================================================
-- Audit Logs + Usage Metering Tables
-- Date: 2026-02-18
-- ============================================================================

BEGIN;

-- ============================================================================
-- 1. Audit Logs — who did what, when
-- ============================================================================

CREATE TABLE IF NOT EXISTS audit_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id TEXT NOT NULL,
  action TEXT NOT NULL,             -- e.g., 'account.connect', 'settings.update', 'team.invite'
  resource_type TEXT,               -- e.g., 'account', 'workspace', 'post'
  resource_id TEXT,                 -- ID of the affected resource
  metadata JSONB DEFAULT '{}',     -- Additional context (old/new values, etc.)
  ip_address TEXT,
  user_agent TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for user-scoped queries
CREATE INDEX IF NOT EXISTS idx_audit_logs_user_created ON audit_logs(user_id, created_at DESC);

-- Index for resource-scoped queries
CREATE INDEX IF NOT EXISTS idx_audit_logs_resource ON audit_logs(resource_type, resource_id, created_at DESC);

-- Index for action filtering
CREATE INDEX IF NOT EXISTS idx_audit_logs_action ON audit_logs(action, created_at DESC);

-- RLS: backend-only table (service_role inserts, users can read own)
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users read own audit logs"
  ON audit_logs FOR SELECT
  USING ((SELECT auth.uid())::text = user_id);

-- ============================================================================
-- 2. API Usage Metering — track calls per user per endpoint per period
-- ============================================================================

CREATE TABLE IF NOT EXISTS api_usage (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id TEXT NOT NULL,
  endpoint TEXT NOT NULL,           -- e.g., 'posts.publish', 'analytics.refresh'
  call_count INTEGER DEFAULT 1,
  period_start DATE NOT NULL DEFAULT CURRENT_DATE,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(user_id, endpoint, period_start)
);

-- Index for user usage dashboard
CREATE INDEX IF NOT EXISTS idx_api_usage_user_period ON api_usage(user_id, period_start DESC);

-- RLS: backend-only inserts, users can read own
ALTER TABLE api_usage ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users read own usage"
  ON api_usage FOR SELECT
  USING ((SELECT auth.uid())::text = user_id);

-- ============================================================================
-- 3. Upsert function for usage tracking (atomic increment)
-- ============================================================================

CREATE OR REPLACE FUNCTION increment_api_usage(
  p_user_id TEXT,
  p_endpoint TEXT
)
RETURNS VOID
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
BEGIN
  INSERT INTO api_usage (user_id, endpoint, call_count, period_start)
  VALUES (p_user_id, p_endpoint, 1, CURRENT_DATE)
  ON CONFLICT (user_id, endpoint, period_start)
  DO UPDATE SET
    call_count = api_usage.call_count + 1,
    updated_at = NOW();
END;
$$;

-- ============================================================================
-- 4. Auto-cleanup: drop audit logs older than 90 days (run via cron)
-- ============================================================================

CREATE OR REPLACE FUNCTION cleanup_old_audit_logs()
RETURNS INTEGER
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
  deleted_count INTEGER;
BEGIN
  DELETE FROM audit_logs
  WHERE created_at < NOW() - INTERVAL '90 days';
  GET DIAGNOSTICS deleted_count = ROW_COUNT;
  RETURN deleted_count;
END;
$$;

COMMIT;

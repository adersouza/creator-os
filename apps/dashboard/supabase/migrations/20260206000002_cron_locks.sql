-- Migration: Cron Locks — Distributed locking for cron jobs
-- Date: 2026-02-06
-- Purpose: Prevent concurrent cron runs from processing the same job

-- ============================================================================
-- Cron Locks Table
-- ============================================================================

CREATE TABLE IF NOT EXISTS cron_locks (
  job_name TEXT PRIMARY KEY,
  locked_at TIMESTAMPTZ,
  locked_by TEXT,  -- Instance ID or hostname
  expires_at TIMESTAMPTZ
);

-- ============================================================================
-- Function: Acquire a cron lock with TTL
-- ============================================================================
-- Attempts to acquire a lock. Returns TRUE if acquired, FALSE if another
-- instance holds a non-expired lock.
--
-- Usage:
--   SELECT acquire_cron_lock('scheduled-posts', 'instance-uuid', 55);

CREATE OR REPLACE FUNCTION acquire_cron_lock(
  p_job_name TEXT,
  p_locked_by TEXT,
  p_ttl_seconds INT DEFAULT 55
) RETURNS BOOLEAN AS $$
DECLARE
  v_acquired BOOLEAN;
BEGIN
  -- Try to insert or update expired lock
  INSERT INTO cron_locks (job_name, locked_at, locked_by, expires_at)
  VALUES (p_job_name, NOW(), p_locked_by, NOW() + (p_ttl_seconds || ' seconds')::INTERVAL)
  ON CONFLICT (job_name) DO UPDATE
  SET locked_at = NOW(),
      locked_by = p_locked_by,
      expires_at = NOW() + (p_ttl_seconds || ' seconds')::INTERVAL
  WHERE cron_locks.expires_at < NOW();

  -- Check if we got the lock
  SELECT locked_by = p_locked_by INTO v_acquired
  FROM cron_locks WHERE job_name = p_job_name;

  RETURN COALESCE(v_acquired, FALSE);
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- Function: Release a cron lock
-- ============================================================================

CREATE OR REPLACE FUNCTION release_cron_lock(
  p_job_name TEXT,
  p_locked_by TEXT
) RETURNS VOID AS $$
BEGIN
  DELETE FROM cron_locks WHERE job_name = p_job_name AND locked_by = p_locked_by;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- Permissions
-- ============================================================================

GRANT ALL ON cron_locks TO service_role;
GRANT EXECUTE ON FUNCTION acquire_cron_lock TO service_role;
GRANT EXECUTE ON FUNCTION release_cron_lock TO service_role;

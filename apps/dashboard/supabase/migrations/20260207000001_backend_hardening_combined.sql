-- Combined Backend Hardening Migration
-- Date: 2026-02-07
-- Combines: cron_locks, cron_runs, ig_pending_containers, threads_webhook_events,
--           retry_columns, indexes, check_ig_endpoint_limit, ig_dm_template_increment_rpc

-- ============================================================================
-- 1. Cron Locks — Distributed locking for cron jobs
-- ============================================================================

CREATE TABLE IF NOT EXISTS cron_locks (
  job_name TEXT PRIMARY KEY,
  locked_at TIMESTAMPTZ,
  locked_by TEXT,
  expires_at TIMESTAMPTZ
);

CREATE OR REPLACE FUNCTION acquire_cron_lock(
  p_job_name TEXT,
  p_locked_by TEXT,
  p_ttl_seconds INT DEFAULT 55
) RETURNS BOOLEAN AS $$
DECLARE
  v_acquired BOOLEAN;
BEGIN
  INSERT INTO cron_locks (job_name, locked_at, locked_by, expires_at)
  VALUES (p_job_name, NOW(), p_locked_by, NOW() + (p_ttl_seconds || ' seconds')::INTERVAL)
  ON CONFLICT (job_name) DO UPDATE
  SET locked_at = NOW(),
      locked_by = p_locked_by,
      expires_at = NOW() + (p_ttl_seconds || ' seconds')::INTERVAL
  WHERE cron_locks.expires_at < NOW();

  SELECT locked_by = p_locked_by INTO v_acquired
  FROM cron_locks WHERE job_name = p_job_name;

  RETURN COALESCE(v_acquired, FALSE);
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION release_cron_lock(
  p_job_name TEXT,
  p_locked_by TEXT
) RETURNS VOID AS $$
BEGIN
  DELETE FROM cron_locks WHERE job_name = p_job_name AND locked_by = p_locked_by;
END;
$$ LANGUAGE plpgsql;

GRANT ALL ON cron_locks TO service_role;
GRANT EXECUTE ON FUNCTION acquire_cron_lock TO service_role;
GRANT EXECUTE ON FUNCTION release_cron_lock TO service_role;

-- ============================================================================
-- 2. Cron Runs — Health monitoring for cron executions
-- ============================================================================

CREATE TABLE IF NOT EXISTS cron_runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  job_name TEXT NOT NULL,
  started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  finished_at TIMESTAMPTZ,
  status TEXT NOT NULL DEFAULT 'running',
  items_processed INT DEFAULT 0,
  error TEXT,
  metadata JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_cron_runs_job_started ON cron_runs(job_name, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_cron_runs_status ON cron_runs(status) WHERE status != 'success';
GRANT ALL ON cron_runs TO service_role;

-- ============================================================================
-- 3. IG Pending Containers — Async Instagram container polling
-- ============================================================================

CREATE TABLE IF NOT EXISTS ig_pending_containers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  post_id TEXT REFERENCES posts(id) ON DELETE CASCADE,
  container_id TEXT NOT NULL,
  account_id UUID NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  last_checked_at TIMESTAMPTZ,
  check_count INT DEFAULT 0,
  error TEXT,
  login_type TEXT DEFAULT 'facebook'
);

CREATE INDEX IF NOT EXISTS idx_pending_containers_status
  ON ig_pending_containers(status)
  WHERE status = 'pending';

ALTER TABLE ig_pending_containers DISABLE ROW LEVEL SECURITY;
GRANT ALL ON ig_pending_containers TO service_role;

-- ============================================================================
-- 4. Threads Webhook Events
-- ============================================================================

CREATE TABLE IF NOT EXISTS threads_webhook_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_type TEXT NOT NULL,
  threads_user_id TEXT NOT NULL,
  payload JSONB NOT NULL,
  received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  processed BOOLEAN NOT NULL DEFAULT false,
  processed_at TIMESTAMPTZ,
  error TEXT,
  retry_count INT DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_threads_webhook_pending
  ON threads_webhook_events(received_at ASC)
  WHERE processed = false;

CREATE INDEX IF NOT EXISTS idx_threads_webhook_type
  ON threads_webhook_events(event_type, received_at DESC);

ALTER TABLE threads_webhook_events DISABLE ROW LEVEL SECURITY;
GRANT ALL ON threads_webhook_events TO service_role;

-- ============================================================================
-- 5. Retry columns for auto_post_queue, ig_webhook_events, threads_webhook_events
-- ============================================================================

ALTER TABLE auto_post_queue ADD COLUMN IF NOT EXISTS retry_count INT DEFAULT 0;
ALTER TABLE auto_post_queue ADD COLUMN IF NOT EXISTS next_retry_at TIMESTAMPTZ;
ALTER TABLE auto_post_queue ADD COLUMN IF NOT EXISTS last_error TEXT;

ALTER TABLE ig_webhook_events ADD COLUMN IF NOT EXISTS next_retry_at TIMESTAMPTZ;
ALTER TABLE ig_webhook_events ADD COLUMN IF NOT EXISTS last_error TEXT;

ALTER TABLE threads_webhook_events ADD COLUMN IF NOT EXISTS next_retry_at TIMESTAMPTZ;
ALTER TABLE threads_webhook_events ADD COLUMN IF NOT EXISTS last_error TEXT;

-- ============================================================================
-- 6. Performance indexes
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_posts_scheduled_pending
  ON posts(scheduled_for)
  WHERE status = 'scheduled';

CREATE INDEX IF NOT EXISTS idx_posts_platform_account
  ON posts(platform, account_id);

CREATE INDEX IF NOT EXISTS idx_posts_published_date
  ON posts(published_at DESC)
  WHERE status = 'published';

CREATE INDEX IF NOT EXISTS idx_auto_post_queue_pending
  ON auto_post_queue(scheduled_for)
  WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_ig_webhook_pending
  ON ig_webhook_events(received_at)
  WHERE processed_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_competitor_posts_fetched
  ON competitor_posts(competitor_id, created_at DESC);

-- rate_limit_tracking index skipped (table may not exist on all environments)

-- ============================================================================
-- 7. IG Endpoint Rate Limits
-- ============================================================================

CREATE TABLE IF NOT EXISTS ig_endpoint_rate_limits (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id UUID NOT NULL,
  endpoint TEXT NOT NULL,
  requests_this_hour INT DEFAULT 0,
  hour_window_start TIMESTAMPTZ DEFAULT NOW(),
  requests_today INT DEFAULT 0,
  day_window_start TIMESTAMPTZ DEFAULT (CURRENT_DATE)::TIMESTAMPTZ,
  last_request_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(account_id, endpoint)
);

CREATE INDEX IF NOT EXISTS idx_ig_endpoint_limits_lookup
  ON ig_endpoint_rate_limits(account_id, endpoint);

CREATE OR REPLACE FUNCTION check_ig_endpoint_limit(
  p_account_id UUID,
  p_endpoint TEXT,
  p_hourly_limit INT,
  p_daily_limit INT
) RETURNS TABLE(allowed BOOLEAN, reason TEXT) AS $$
DECLARE
  v_record ig_endpoint_rate_limits%ROWTYPE;
  v_now TIMESTAMPTZ := NOW();
  v_today DATE := CURRENT_DATE;
  v_hour_ago TIMESTAMPTZ := v_now - INTERVAL '1 hour';
BEGIN
  INSERT INTO ig_endpoint_rate_limits (account_id, endpoint, requests_this_hour, requests_today, hour_window_start, day_window_start)
  VALUES (p_account_id, p_endpoint, 0, 0, v_now, v_today::TIMESTAMPTZ)
  ON CONFLICT (account_id, endpoint) DO UPDATE
  SET last_request_at = v_now
  RETURNING * INTO v_record;

  SELECT * INTO v_record
  FROM ig_endpoint_rate_limits
  WHERE account_id = p_account_id AND endpoint = p_endpoint
  FOR UPDATE;

  IF v_record.hour_window_start < v_hour_ago THEN
    v_record.requests_this_hour := 0;
    v_record.hour_window_start := v_now;
  END IF;

  IF v_record.day_window_start::DATE < v_today THEN
    v_record.requests_today := 0;
    v_record.day_window_start := v_today::TIMESTAMPTZ;
  END IF;

  IF p_hourly_limit > 0 AND v_record.requests_this_hour >= p_hourly_limit THEN
    RETURN QUERY SELECT
      FALSE,
      FORMAT('Hourly limit reached (%s/%s) for %s', v_record.requests_this_hour, p_hourly_limit, p_endpoint);
    RETURN;
  END IF;

  IF p_daily_limit > 0 AND v_record.requests_today >= p_daily_limit THEN
    RETURN QUERY SELECT
      FALSE,
      FORMAT('Daily limit reached (%s/%s) for %s', v_record.requests_today, p_daily_limit, p_endpoint);
    RETURN;
  END IF;

  UPDATE ig_endpoint_rate_limits
  SET
    requests_this_hour = v_record.requests_this_hour + 1,
    requests_today = v_record.requests_today + 1,
    hour_window_start = v_record.hour_window_start,
    day_window_start = v_record.day_window_start,
    last_request_at = v_now
  WHERE account_id = p_account_id AND endpoint = p_endpoint;

  RETURN QUERY SELECT TRUE, NULL::TEXT;
END;
$$ LANGUAGE plpgsql;

GRANT ALL ON ig_endpoint_rate_limits TO service_role;
GRANT EXECUTE ON FUNCTION check_ig_endpoint_limit TO service_role;

-- ============================================================================
-- 8. DM Template Increment RPC
-- ============================================================================

CREATE OR REPLACE FUNCTION increment_dm_template_use(
  p_template_id uuid,
  p_user_id uuid
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
  UPDATE ig_dm_templates
  SET
    use_count = COALESCE(use_count, 0) + 1,
    updated_at = now()
  WHERE
    id = p_template_id
    AND user_id = p_user_id;
END;
$$;

GRANT EXECUTE ON FUNCTION increment_dm_template_use(uuid, uuid) TO authenticated;
GRANT EXECUTE ON FUNCTION increment_dm_template_use(uuid, uuid) TO service_role;

-- Enterprise hardening: webhook secret rotation + auth lockout tracking
-- Addresses audit gaps #1 (webhook rotation) and #3 (auth lockout)

-- ============================================================================
-- #1: Webhook Secret Rotation
-- ============================================================================

-- Track when secrets were last rotated and when they expire
ALTER TABLE webhook_subscriptions
  ADD COLUMN IF NOT EXISTS secret_rotated_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS secret_expires_at TIMESTAMPTZ;

-- Index for cron to find expiring secrets efficiently
CREATE INDEX IF NOT EXISTS idx_webhook_subs_secret_expires
  ON webhook_subscriptions(secret_expires_at)
  WHERE secret IS NOT NULL AND secret_expires_at IS NOT NULL AND active = true;

-- ============================================================================
-- #3: Auth Attempt Lockout
-- ============================================================================

-- Track failed auth attempts per IP for lockout (Redis is primary, this is audit trail)
CREATE TABLE IF NOT EXISTS auth_lockout_log (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  identifier TEXT NOT NULL,           -- IP address or API key prefix
  identifier_type TEXT NOT NULL,      -- 'ip' or 'api_key'
  attempts INTEGER NOT NULL DEFAULT 1,
  locked_until TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- RLS: only service role can read/write lockout logs
ALTER TABLE auth_lockout_log ENABLE ROW LEVEL SECURITY;

-- Index for lookup by identifier. Partial on unresolved lockouts; the
-- "> NOW()" condition was removed — PG rejects it because NOW() is STABLE,
-- not IMMUTABLE. Query-side predicate still filters expired rows.
CREATE INDEX IF NOT EXISTS idx_auth_lockout_identifier
  ON auth_lockout_log(identifier, identifier_type)
  WHERE locked_until IS NULL;

-- Cleanup lookup by age. Can't use a NOW()-relative partial (same IMMUTABLE
-- constraint), so this is a plain btree on created_at. The daily cleanup job
-- scans and deletes rows older than 7 days using this index.
CREATE INDEX IF NOT EXISTS idx_auth_lockout_cleanup
  ON auth_lockout_log(created_at);

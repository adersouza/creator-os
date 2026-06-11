-- Outgoing webhook delivery tracking with retry support
-- Pro/Empire tiers get reliable delivery; Free tier remains fire-and-forget.

CREATE TABLE IF NOT EXISTS webhook_deliveries (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  subscription_id UUID NOT NULL REFERENCES webhook_subscriptions(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  event TEXT NOT NULL,
  payload JSONB NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',  -- pending | delivered | failed | dead_letter
  attempts INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 3,
  last_attempt_at TIMESTAMPTZ,
  next_retry_at TIMESTAMPTZ,
  last_error TEXT,
  delivered_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index for the retry cron: find pending/failed deliveries due for retry
CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_retry
  ON webhook_deliveries(status, next_retry_at)
  WHERE status IN ('pending', 'failed');

-- Index for user-scoped queries (viewing delivery history)
CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_user
  ON webhook_deliveries(user_id, created_at DESC);

-- Cleanup index for old delivered/dead_letter entries
CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_cleanup
  ON webhook_deliveries(created_at)
  WHERE status IN ('delivered', 'dead_letter');

-- RLS: service-role-only (accessed by API routes only)
ALTER TABLE webhook_deliveries ENABLE ROW LEVEL SECURITY;

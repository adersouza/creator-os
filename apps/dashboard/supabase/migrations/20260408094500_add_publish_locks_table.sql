-- DB fallback lock for autoposter publishes when Redis is unavailable.
-- Keeps concurrency protection fail-closed instead of allowing double-publish.

CREATE TABLE IF NOT EXISTS public.publish_locks (
  account_id TEXT PRIMARY KEY,
  owner_token TEXT NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_publish_locks_expires_at
  ON public.publish_locks (expires_at);

REVOKE ALL ON public.publish_locks FROM PUBLIC;
REVOKE ALL ON public.publish_locks FROM anon;
REVOKE ALL ON public.publish_locks FROM authenticated;
GRANT ALL ON public.publish_locks TO service_role;

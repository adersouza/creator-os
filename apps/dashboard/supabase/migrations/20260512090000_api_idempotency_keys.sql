CREATE TABLE IF NOT EXISTS public.api_idempotency_keys (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  route TEXT NOT NULL,
  action TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  payload_hash TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'processing' CHECK (status IN ('processing', 'completed', 'failed')),
  response_status INTEGER,
  response_body JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  completed_at TIMESTAMPTZ,
  expires_at TIMESTAMPTZ NOT NULL DEFAULT NOW() + INTERVAL '24 hours',
  UNIQUE (user_id, route, action, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_api_idempotency_keys_expiry
  ON public.api_idempotency_keys(expires_at);

CREATE INDEX IF NOT EXISTS idx_api_idempotency_keys_lookup
  ON public.api_idempotency_keys(user_id, route, action, idempotency_key, status);

ALTER TABLE public.api_idempotency_keys ENABLE ROW LEVEL SECURITY;

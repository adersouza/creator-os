-- Meta Data Deletion Request tracking.
-- Stores confirmation codes from Meta's data-deletion callback so the
-- verification URL works and we can schedule + track the actual cascade.

CREATE TABLE IF NOT EXISTS data_deletion_requests (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  confirmation_code UUID NOT NULL UNIQUE,
  meta_user_id TEXT NOT NULL,
  user_id TEXT,  -- resolved from accounts/instagram_accounts, nullable if not found
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'processing', 'completed', 'failed', 'no_data_found')),
  requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ,
  error_message TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_ddr_confirmation_code ON data_deletion_requests(confirmation_code);
CREATE INDEX idx_ddr_meta_user_id ON data_deletion_requests(meta_user_id);
CREATE INDEX idx_ddr_status ON data_deletion_requests(status) WHERE status IN ('pending', 'processing');

-- RLS: only service_role can read/write (Meta callback + cron + process-deletion)
ALTER TABLE data_deletion_requests ENABLE ROW LEVEL SECURITY;

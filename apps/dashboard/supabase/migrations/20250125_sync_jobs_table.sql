-- Sync Jobs Table for Realtime Progress Updates
-- This replaces polling with push-based updates via Supabase Realtime

CREATE TABLE IF NOT EXISTS sync_jobs (
  id TEXT PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'processing', 'completed', 'failed')),
  account_count INTEGER NOT NULL DEFAULT 0,
  current_progress INTEGER NOT NULL DEFAULT 0,
  current_account TEXT,
  success_count INTEGER NOT NULL DEFAULT 0,
  failed_count INTEGER NOT NULL DEFAULT 0,
  suspended_accounts TEXT[] DEFAULT '{}',
  reactivated_accounts TEXT[] DEFAULT '{}',
  error_message TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  started_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index for user lookups
CREATE INDEX IF NOT EXISTS idx_sync_jobs_user_id ON sync_jobs(user_id);

-- Index for finding active jobs
CREATE INDEX IF NOT EXISTS idx_sync_jobs_status ON sync_jobs(status) WHERE status IN ('queued', 'processing');

-- RLS policies
ALTER TABLE sync_jobs ENABLE ROW LEVEL SECURITY;

-- Users can only see their own jobs
CREATE POLICY "Users can view own sync jobs"
  ON sync_jobs FOR SELECT
  USING (auth.uid() = user_id);

-- Service role can insert/update (API routes use service key)
CREATE POLICY "Service role can manage sync jobs"
  ON sync_jobs FOR ALL
  USING (true)
  WITH CHECK (true);

-- Enable Realtime for this table
ALTER PUBLICATION supabase_realtime ADD TABLE sync_jobs;

-- Function to auto-update updated_at
CREATE OR REPLACE FUNCTION update_sync_jobs_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER sync_jobs_updated_at
  BEFORE UPDATE ON sync_jobs
  FOR EACH ROW
  EXECUTE FUNCTION update_sync_jobs_updated_at();

-- Cleanup old jobs (older than 24 hours)
CREATE OR REPLACE FUNCTION cleanup_old_sync_jobs()
RETURNS void AS $$
BEGIN
  DELETE FROM sync_jobs WHERE created_at < NOW() - INTERVAL '24 hours';
END;
$$ LANGUAGE plpgsql;

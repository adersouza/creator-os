CREATE TABLE IF NOT EXISTS data_export_jobs (
  id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
  user_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'complete', 'failed')),
  file_path TEXT,
  error_message TEXT,
  expires_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now(),
  completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_data_export_jobs_user ON data_export_jobs(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_data_export_jobs_cleanup ON data_export_jobs(expires_at) WHERE status = 'complete';

ALTER TABLE data_export_jobs ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users manage own exports" ON data_export_jobs
  FOR ALL USING (auth.uid()::text = user_id);

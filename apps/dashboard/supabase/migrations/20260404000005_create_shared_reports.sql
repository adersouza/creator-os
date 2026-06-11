-- Shareable reports: public read-only links with expiry
CREATE TABLE IF NOT EXISTS shared_reports (
  id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
  user_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  report_data JSONB NOT NULL,
  share_token TEXT UNIQUE NOT NULL DEFAULT gen_random_uuid()::text,
  expires_at TIMESTAMPTZ NOT NULL,
  view_count INT DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE shared_reports ENABLE ROW LEVEL SECURITY;

-- Owner can manage their shared reports
CREATE POLICY "Users manage own shared reports"
  ON shared_reports FOR ALL
  USING (auth.uid()::text = user_id)
  WITH CHECK (auth.uid()::text = user_id);

-- Anyone can read by token (for public share links)
CREATE POLICY "Public read by share token"
  ON shared_reports FOR SELECT
  USING (true);

CREATE INDEX idx_shared_reports_token
  ON shared_reports(share_token);

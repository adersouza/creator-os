-- Scheduled report delivery: automated weekly/monthly reports
CREATE TABLE IF NOT EXISTS report_schedules (
  id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
  user_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  account_id TEXT NOT NULL,
  schedule_type TEXT NOT NULL CHECK (schedule_type IN ('weekly', 'monthly')),
  report_type TEXT NOT NULL CHECK (report_type IN ('weekly', 'monthly', 'custom')),
  day_of_week INT CHECK (day_of_week BETWEEN 0 AND 6),
  day_of_month INT CHECK (day_of_month BETWEEN 1 AND 28),
  recipient_emails TEXT[] DEFAULT '{}',
  include_recommendations BOOLEAN DEFAULT true,
  client_name TEXT,
  platform TEXT DEFAULT 'threads',
  is_active BOOLEAN DEFAULT true,
  last_sent_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE report_schedules ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users manage own report schedules"
  ON report_schedules FOR ALL
  USING (auth.uid()::text = user_id)
  WITH CHECK (auth.uid()::text = user_id);

CREATE INDEX idx_report_schedules_user
  ON report_schedules(user_id, is_active);

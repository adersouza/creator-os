-- Chart annotations: user-created markers on time-series charts
-- (algorithm changes, campaigns, viral posts, events)
CREATE TABLE IF NOT EXISTS chart_annotations (
  id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
  user_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  annotation_date DATE NOT NULL,
  label TEXT NOT NULL CHECK (char_length(label) <= 200),
  color TEXT DEFAULT '#38bdf8',
  annotation_type TEXT DEFAULT 'line' CHECK (annotation_type IN ('line', 'area')),
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE (user_id, account_id, annotation_date, label)
);

ALTER TABLE chart_annotations ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users manage own annotations"
  ON chart_annotations FOR ALL
  USING (auth.uid()::text = user_id)
  WITH CHECK (auth.uid()::text = user_id);

CREATE INDEX idx_chart_annotations_account
  ON chart_annotations(account_id, annotation_date);

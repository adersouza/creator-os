-- #568: Create quick_wins table
-- Referenced by api/v1/insights.ts, api/recap/generate.ts, api/user/annual-recap.ts

CREATE TABLE IF NOT EXISTS quick_wins (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id text NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  account_id text NOT NULL,
  title text NOT NULL,
  description text,
  category text NOT NULL DEFAULT 'general',
  priority integer NOT NULL DEFAULT 0,
  status text NOT NULL DEFAULT 'pending', -- pending, in_progress, completed, dismissed
  measured_impact real,
  completed_at timestamptz,
  created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now()
);

ALTER TABLE quick_wins ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users manage own quick wins" ON quick_wins
  FOR ALL USING (user_id = (SELECT auth.uid()::text))
  WITH CHECK (user_id = (SELECT auth.uid()::text));

CREATE INDEX IF NOT EXISTS idx_quick_wins_user_id ON quick_wins (user_id);
CREATE INDEX IF NOT EXISTS idx_quick_wins_account_id ON quick_wins (account_id);
CREATE INDEX IF NOT EXISTS idx_quick_wins_status ON quick_wins (status);

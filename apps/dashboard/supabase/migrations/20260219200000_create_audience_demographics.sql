CREATE TABLE IF NOT EXISTS audience_demographics (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  account_id text NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  instagram_account_id uuid REFERENCES instagram_accounts(id) ON DELETE CASCADE,
  platform text NOT NULL CHECK (platform IN ('threads', 'instagram')),
  fetched_at timestamptz DEFAULT now(),
  fetched_date date DEFAULT CURRENT_DATE,
  breakdown_type text NOT NULL CHECK (breakdown_type IN ('age', 'gender', 'city', 'country')),
  breakdown_value text NOT NULL,
  count numeric NOT NULL DEFAULT 0,
  percentage numeric
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_demographics_unique ON audience_demographics(account_id, platform, breakdown_type, breakdown_value, fetched_date);

-- RLS
ALTER TABLE audience_demographics ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can view own demographics via threads" ON audience_demographics FOR SELECT USING (
  account_id IN (SELECT id FROM accounts WHERE user_id = auth.uid()::text)
);
CREATE POLICY "Users can view own demographics via instagram" ON audience_demographics FOR SELECT USING (
  instagram_account_id IN (SELECT id FROM instagram_accounts WHERE user_id = auth.uid()::text)
);

CREATE INDEX IF NOT EXISTS idx_demographics_account ON audience_demographics(account_id, platform, fetched_at);
CREATE INDEX IF NOT EXISTS idx_demographics_ig_account ON audience_demographics(instagram_account_id, fetched_at);

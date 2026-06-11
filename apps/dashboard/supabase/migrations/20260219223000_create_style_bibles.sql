-- Style Bible: stores user's writing style profile extracted from sample captions
CREATE TABLE IF NOT EXISTS style_bibles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  account_id TEXT, -- nullable, links to specific social account
  sample_captions JSONB NOT NULL DEFAULT '[]'::jsonb,
  extracted_profile JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One style bible per user+account combo
CREATE UNIQUE INDEX IF NOT EXISTS idx_style_bibles_user_account
  ON style_bibles (user_id, COALESCE(account_id, '__global__'));

CREATE INDEX IF NOT EXISTS idx_style_bibles_user_id ON style_bibles (user_id);

-- RLS
ALTER TABLE style_bibles ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can manage own style bibles"
  ON style_bibles FOR ALL
  USING (auth.uid() = user_id)
  WITH CHECK (auth.uid() = user_id);

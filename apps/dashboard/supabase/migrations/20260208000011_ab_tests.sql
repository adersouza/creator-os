-- A/B Tests table
CREATE TABLE IF NOT EXISTS ab_tests (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id TEXT REFERENCES profiles(id) ON DELETE CASCADE,
  account_id TEXT REFERENCES accounts(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  test_type TEXT NOT NULL, -- 'hook', 'cta', 'emoji', 'length', 'tone', 'full_content'
  hypothesis TEXT,
  status TEXT DEFAULT 'active', -- 'active', 'completed', 'cancelled'
  winner_variant_id UUID,
  confidence_level DECIMAL(5,4),
  created_at TIMESTAMPTZ DEFAULT NOW(),
  completed_at TIMESTAMPTZ
);

-- Variants within a test
CREATE TABLE IF NOT EXISTS ab_test_variants (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  test_id UUID REFERENCES ab_tests(id) ON DELETE CASCADE,
  post_id TEXT REFERENCES posts(id) ON DELETE SET NULL,
  variant_label TEXT NOT NULL, -- 'A', 'B', 'C', etc.
  content TEXT NOT NULL,
  change_description TEXT,
  views INT DEFAULT 0,
  likes INT DEFAULT 0,
  replies INT DEFAULT 0,
  reposts INT DEFAULT 0,
  quotes INT DEFAULT 0,
  engagement_rate DECIMAL(5,4),
  is_winner BOOLEAN DEFAULT false,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  published_at TIMESTAMPTZ
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_ab_tests_user ON ab_tests(user_id);
CREATE INDEX IF NOT EXISTS idx_ab_tests_account ON ab_tests(account_id);
CREATE INDEX IF NOT EXISTS idx_ab_tests_status ON ab_tests(status) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_ab_test_variants_test ON ab_test_variants(test_id);
CREATE INDEX IF NOT EXISTS idx_ab_test_variants_post ON ab_test_variants(post_id);

-- RLS
ALTER TABLE ab_tests ENABLE ROW LEVEL SECURITY;
ALTER TABLE ab_test_variants ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can manage their own tests" ON ab_tests
  FOR ALL USING (auth.uid()::text = user_id);

CREATE POLICY "Users can manage variants of their tests" ON ab_test_variants
  FOR ALL USING (
    EXISTS (SELECT 1 FROM ab_tests WHERE ab_tests.id = test_id AND ab_tests.user_id = auth.uid()::text)
  );

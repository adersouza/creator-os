-- Add sync cohort columns to accounts and instagram_accounts
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS sync_cohort TEXT DEFAULT 'warm';
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS cohort_updated_at TIMESTAMPTZ;

ALTER TABLE instagram_accounts ADD COLUMN IF NOT EXISTS sync_cohort TEXT DEFAULT 'warm';
ALTER TABLE instagram_accounts ADD COLUMN IF NOT EXISTS cohort_updated_at TIMESTAMPTZ;

-- Index for dispatcher queries
CREATE INDEX IF NOT EXISTS idx_accounts_sync_cohort ON accounts(sync_cohort);
CREATE INDEX IF NOT EXISTS idx_ig_accounts_sync_cohort ON instagram_accounts(sync_cohort);

-- Function to classify accounts into cohorts
CREATE OR REPLACE FUNCTION classify_account_cohorts()
RETURNS INTEGER AS $$
DECLARE
  v_count INTEGER := 0;
  v_rows INTEGER;
BEGIN
  -- Hot: posted in last 24h OR >1000 followers
  UPDATE accounts SET sync_cohort = 'hot', cohort_updated_at = NOW()
  WHERE threads_access_token_encrypted IS NOT NULL
    AND (
      followers_count >= 1000
      OR id IN (
        SELECT DISTINCT account_id FROM posts
        WHERE status = 'published'
          AND published_at > NOW() - INTERVAL '24 hours'
      )
    )
    AND (sync_cohort IS DISTINCT FROM 'hot' OR cohort_updated_at IS NULL OR cohort_updated_at < NOW() - INTERVAL '6 hours');
  GET DIAGNOSTICS v_rows = ROW_COUNT;
  v_count := v_count + v_rows;

  -- Warm: posted in last 7d (but not hot)
  UPDATE accounts SET sync_cohort = 'warm', cohort_updated_at = NOW()
  WHERE threads_access_token_encrypted IS NOT NULL
    AND sync_cohort != 'hot'
    AND id IN (
      SELECT DISTINCT account_id FROM posts
      WHERE status = 'published'
        AND published_at > NOW() - INTERVAL '7 days'
    )
    AND (sync_cohort IS DISTINCT FROM 'warm' OR cohort_updated_at IS NULL OR cohort_updated_at < NOW() - INTERVAL '6 hours');
  GET DIAGNOSTICS v_rows = ROW_COUNT;
  v_count := v_count + v_rows;

  -- Cold: no posts in last 7d but has posts in last 30d
  UPDATE accounts SET sync_cohort = 'cold', cohort_updated_at = NOW()
  WHERE threads_access_token_encrypted IS NOT NULL
    AND sync_cohort NOT IN ('hot', 'warm')
    AND id IN (
      SELECT DISTINCT account_id FROM posts
      WHERE status = 'published'
        AND published_at > NOW() - INTERVAL '30 days'
    )
    AND id NOT IN (
      SELECT DISTINCT account_id FROM posts
      WHERE status = 'published'
        AND published_at > NOW() - INTERVAL '7 days'
    )
    AND (sync_cohort IS DISTINCT FROM 'cold' OR cohort_updated_at IS NULL OR cohort_updated_at < NOW() - INTERVAL '6 hours');
  GET DIAGNOSTICS v_rows = ROW_COUNT;
  v_count := v_count + v_rows;

  -- Dormant: everything else
  UPDATE accounts SET sync_cohort = 'dormant', cohort_updated_at = NOW()
  WHERE threads_access_token_encrypted IS NOT NULL
    AND sync_cohort NOT IN ('hot', 'warm', 'cold')
    AND (sync_cohort IS DISTINCT FROM 'dormant' OR cohort_updated_at IS NULL OR cohort_updated_at < NOW() - INTERVAL '6 hours');
  GET DIAGNOSTICS v_rows = ROW_COUNT;
  v_count := v_count + v_rows;

  -- Same for Instagram accounts
  UPDATE instagram_accounts SET sync_cohort = 'hot', cohort_updated_at = NOW()
  WHERE instagram_access_token_encrypted IS NOT NULL
    AND (
      followers_count >= 1000
      OR id IN (
        SELECT DISTINCT instagram_account_id FROM posts
        WHERE platform = 'instagram'
          AND status = 'published'
          AND instagram_account_id IS NOT NULL
          AND published_at > NOW() - INTERVAL '24 hours'
      )
    )
    AND (sync_cohort IS DISTINCT FROM 'hot' OR cohort_updated_at IS NULL OR cohort_updated_at < NOW() - INTERVAL '6 hours');

  UPDATE instagram_accounts SET sync_cohort = 'warm', cohort_updated_at = NOW()
  WHERE instagram_access_token_encrypted IS NOT NULL
    AND sync_cohort != 'hot'
    AND id IN (
      SELECT DISTINCT instagram_account_id FROM posts
      WHERE platform = 'instagram'
        AND status = 'published'
        AND instagram_account_id IS NOT NULL
        AND published_at > NOW() - INTERVAL '7 days'
    )
    AND (sync_cohort IS DISTINCT FROM 'warm' OR cohort_updated_at IS NULL OR cohort_updated_at < NOW() - INTERVAL '6 hours');

  UPDATE instagram_accounts SET sync_cohort = 'cold', cohort_updated_at = NOW()
  WHERE instagram_access_token_encrypted IS NOT NULL
    AND sync_cohort NOT IN ('hot', 'warm')
    AND id IN (
      SELECT DISTINCT instagram_account_id FROM posts
      WHERE platform = 'instagram'
        AND status = 'published'
        AND instagram_account_id IS NOT NULL
        AND published_at > NOW() - INTERVAL '30 days'
    )
    AND id NOT IN (
      SELECT DISTINCT instagram_account_id FROM posts
      WHERE platform = 'instagram'
        AND status = 'published'
        AND instagram_account_id IS NOT NULL
        AND published_at > NOW() - INTERVAL '7 days'
    )
    AND (sync_cohort IS DISTINCT FROM 'cold' OR cohort_updated_at IS NULL OR cohort_updated_at < NOW() - INTERVAL '6 hours');

  UPDATE instagram_accounts SET sync_cohort = 'dormant', cohort_updated_at = NOW()
  WHERE instagram_access_token_encrypted IS NOT NULL
    AND sync_cohort NOT IN ('hot', 'warm', 'cold')
    AND (sync_cohort IS DISTINCT FROM 'dormant' OR cohort_updated_at IS NULL OR cohort_updated_at < NOW() - INTERVAL '6 hours');

  RETURN v_count;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public;

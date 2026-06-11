-- Fix NULL cohort classification bug
-- In PostgreSQL, NULL NOT IN (...) evaluates to NULL (falsy), so accounts with
-- sync_cohort = NULL were never matched by the warm, cold, or dormant clauses.
-- Fix: add OR sync_cohort IS NULL to those WHERE clauses for both tables.
CREATE OR REPLACE FUNCTION classify_account_cohorts() RETURNS INTEGER AS $$
DECLARE v_count INTEGER := 0; v_rows INTEGER;
BEGIN
  UPDATE accounts SET sync_cohort = 'hot', cohort_updated_at = NOW()
  WHERE threads_access_token_encrypted IS NOT NULL AND (
    followers_count >= 500 OR id IN (SELECT DISTINCT account_id FROM posts WHERE status = 'published' AND published_at > NOW() - INTERVAL '24 hours')
    OR last_synced_at > NOW() - INTERVAL '2 hours')
  AND (sync_cohort IS DISTINCT FROM 'hot' OR cohort_updated_at IS NULL OR cohort_updated_at < NOW() - INTERVAL '6 hours');
  GET DIAGNOSTICS v_rows = ROW_COUNT; v_count := v_count + v_rows;
  UPDATE accounts SET sync_cohort = 'warm', cohort_updated_at = NOW()
  WHERE threads_access_token_encrypted IS NOT NULL AND (sync_cohort != 'hot' OR sync_cohort IS NULL)
  AND id IN (SELECT DISTINCT account_id FROM posts WHERE status = 'published' AND published_at > NOW() - INTERVAL '7 days')
  AND (sync_cohort IS DISTINCT FROM 'warm' OR cohort_updated_at IS NULL OR cohort_updated_at < NOW() - INTERVAL '6 hours');
  GET DIAGNOSTICS v_rows = ROW_COUNT; v_count := v_count + v_rows;
  UPDATE accounts SET sync_cohort = 'cold', cohort_updated_at = NOW()
  WHERE threads_access_token_encrypted IS NOT NULL AND (sync_cohort NOT IN ('hot', 'warm') OR sync_cohort IS NULL)
  AND id IN (SELECT DISTINCT account_id FROM posts WHERE status = 'published' AND published_at > NOW() - INTERVAL '30 days')
  AND id NOT IN (SELECT DISTINCT account_id FROM posts WHERE status = 'published' AND published_at > NOW() - INTERVAL '7 days')
  AND (sync_cohort IS DISTINCT FROM 'cold' OR cohort_updated_at IS NULL OR cohort_updated_at < NOW() - INTERVAL '6 hours');
  GET DIAGNOSTICS v_rows = ROW_COUNT; v_count := v_count + v_rows;
  UPDATE accounts SET sync_cohort = 'dormant', cohort_updated_at = NOW()
  WHERE threads_access_token_encrypted IS NOT NULL AND (sync_cohort NOT IN ('hot', 'warm', 'cold') OR sync_cohort IS NULL)
  AND (sync_cohort IS DISTINCT FROM 'dormant' OR cohort_updated_at IS NULL OR cohort_updated_at < NOW() - INTERVAL '6 hours');
  GET DIAGNOSTICS v_rows = ROW_COUNT; v_count := v_count + v_rows;
  UPDATE instagram_accounts SET sync_cohort = 'hot', cohort_updated_at = NOW()
  WHERE instagram_access_token_encrypted IS NOT NULL AND (followers_count >= 500
    OR id IN (SELECT DISTINCT instagram_account_id FROM posts WHERE platform = 'instagram' AND status = 'published' AND instagram_account_id IS NOT NULL AND published_at > NOW() - INTERVAL '24 hours')
    OR last_synced_at > NOW() - INTERVAL '2 hours')
  AND (sync_cohort IS DISTINCT FROM 'hot' OR cohort_updated_at IS NULL OR cohort_updated_at < NOW() - INTERVAL '6 hours');
  UPDATE instagram_accounts SET sync_cohort = 'warm', cohort_updated_at = NOW()
  WHERE instagram_access_token_encrypted IS NOT NULL AND (sync_cohort != 'hot' OR sync_cohort IS NULL)
  AND id IN (SELECT DISTINCT instagram_account_id FROM posts WHERE platform = 'instagram' AND status = 'published' AND instagram_account_id IS NOT NULL AND published_at > NOW() - INTERVAL '7 days')
  AND (sync_cohort IS DISTINCT FROM 'warm' OR cohort_updated_at IS NULL OR cohort_updated_at < NOW() - INTERVAL '6 hours');
  UPDATE instagram_accounts SET sync_cohort = 'cold', cohort_updated_at = NOW()
  WHERE instagram_access_token_encrypted IS NOT NULL AND (sync_cohort NOT IN ('hot', 'warm') OR sync_cohort IS NULL)
  AND id IN (SELECT DISTINCT instagram_account_id FROM posts WHERE platform = 'instagram' AND status = 'published' AND instagram_account_id IS NOT NULL AND published_at > NOW() - INTERVAL '30 days')
  AND id NOT IN (SELECT DISTINCT instagram_account_id FROM posts WHERE platform = 'instagram' AND status = 'published' AND instagram_account_id IS NOT NULL AND published_at > NOW() - INTERVAL '7 days')
  AND (sync_cohort IS DISTINCT FROM 'cold' OR cohort_updated_at IS NULL OR cohort_updated_at < NOW() - INTERVAL '6 hours');
  UPDATE instagram_accounts SET sync_cohort = 'dormant', cohort_updated_at = NOW()
  WHERE instagram_access_token_encrypted IS NOT NULL AND (sync_cohort NOT IN ('hot', 'warm', 'cold') OR sync_cohort IS NULL)
  AND (sync_cohort IS DISTINCT FROM 'dormant' OR cohort_updated_at IS NULL OR cohort_updated_at < NOW() - INTERVAL '6 hours');
  RETURN v_count;
END;
$$ LANGUAGE plpgsql;

-- Migration: Add missing indexes for 5 expensive query paths
-- Safe: CREATE INDEX IF NOT EXISTS is idempotent, no table locks on CONCURRENTLY
-- Ref: Query audit 2026-03-07

-- ============================================================================
-- 1. account_daily_summary (account_id, date DESC)
--    Used by: getAnalyticsWithDeltas — 4 sequential queries on this table
--    Currently missing: no composite index on account_daily_summary
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_account_daily_summary_account_date
  ON account_daily_summary(account_id, date DESC);

-- ============================================================================
-- 2. threads_webhook_events (threads_user_id, processed, created_at DESC)
--    Used by: listening/monitor.ts — keyword search scoped by user + processed
--    Existing idx_threads_webhook_type only covers event_type
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_threads_webhook_user_processed_created
  ON threads_webhook_events(threads_user_id, processed, created_at DESC);

-- ============================================================================
-- 3. user_preferences partial index for data_contribution_opted_in
--    Used by: benchmarks.ts — first query in 3-query cascade
--    Speeds up the opt-in filter from seq scan to index scan
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_user_preferences_opted_in
  ON user_preferences(user_id)
  WHERE data_contribution_opted_in = true;

-- ============================================================================
-- 4. ig_comments (ig_user_id) — base index for listening monitor
--    The ILIKE '%keyword%' still needs seq scan on text, but this index
--    lets Postgres filter by ig_user_id first (reduces scan surface)
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_ig_comments_ig_user_id
  ON ig_comments(ig_user_id);

-- ============================================================================
-- 5. ig_mentions (ig_account_id) — same pattern as ig_comments
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_ig_mentions_ig_account_id
  ON ig_mentions(ig_account_id);

-- ============================================================================
-- 6. listening_results (alert_id, checked_at DESC)
--    Used by: monitor.ts dedup check — .eq("alert_id").gte("checked_at")
--    Existing idx_listening_results_alert only covers alert_id
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_listening_results_alert_checked
  ON listening_results(alert_id, checked_at DESC);

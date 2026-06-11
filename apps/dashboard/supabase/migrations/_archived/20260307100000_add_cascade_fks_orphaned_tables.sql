-- Fix: 9 tables with account_id columns had NO foreign key to accounts(id),
-- causing orphaned rows when an account is disconnected.
--
-- Strategy:
--   1. Delete existing orphaned rows (account_id not in accounts)
--   2. Add FK with ON DELETE CASCADE so future deletes are automatic
--
-- Rollback: DROP each CONSTRAINT by name (all named consistently).
--
-- Tables covered:
--   account_analytics, account_daily_summary, post_metric_history,
--   rate_limit_tracking, recommendation_baselines, recommendation_dismissals,
--   creator_events, quick_wins, style_bibles
--
-- Tables NOT touched (already have FKs):
--   auto_post_queue (workspace_id CASCADE, account_id nullable)
--   sent_replies (account_id ON DELETE SET NULL — intentional, preserves reply history)
--   mentions (account_id ON DELETE SET NULL — intentional, preserves mention history)

-- ══════════════════════════════════════════════════════════════════════════════
-- 1. account_analytics
--    account_id was UUID originally, migrated to TEXT via uuid_to_text migration.
--    No FK ever existed.
-- ══════════════════════════════════════════════════════════════════════════════

DELETE FROM account_analytics
WHERE account_id::text NOT IN (SELECT id FROM accounts);

ALTER TABLE account_analytics
  ALTER COLUMN account_id TYPE text USING account_id::text;

ALTER TABLE account_analytics
  ADD CONSTRAINT fk_account_analytics_account
  FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;

-- ══════════════════════════════════════════════════════════════════════════════
-- 2. account_daily_summary
--    Has user_id FK (CASCADE) but no account_id FK.
-- ══════════════════════════════════════════════════════════════════════════════

DELETE FROM account_daily_summary
WHERE account_id NOT IN (SELECT id FROM accounts);

ALTER TABLE account_daily_summary
  ADD CONSTRAINT fk_account_daily_summary_account
  FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;

-- ══════════════════════════════════════════════════════════════════════════════
-- 3. post_metric_history
--    Has post_id FK (CASCADE) but no account_id FK.
-- ══════════════════════════════════════════════════════════════════════════════

DELETE FROM post_metric_history
WHERE account_id NOT IN (SELECT id FROM accounts);

ALTER TABLE post_metric_history
  ADD CONSTRAINT fk_post_metric_history_account
  FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;

-- ══════════════════════════════════════════════════════════════════════════════
-- 4. rate_limit_tracking
--    Originally had FK in 20260121 migration, but 20260218 consolidated migration
--    recreated without it. Column was UUID, migrated to TEXT in 20260222.
-- ══════════════════════════════════════════════════════════════════════════════

DELETE FROM rate_limit_tracking
WHERE account_id NOT IN (SELECT id FROM accounts);

ALTER TABLE rate_limit_tracking
  ADD CONSTRAINT fk_rate_limit_tracking_account
  FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;

-- ══════════════════════════════════════════════════════════════════════════════
-- 5. recommendation_baselines
-- ══════════════════════════════════════════════════════════════════════════════

DELETE FROM recommendation_baselines
WHERE account_id NOT IN (SELECT id FROM accounts);

ALTER TABLE recommendation_baselines
  ADD CONSTRAINT fk_recommendation_baselines_account
  FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;

-- ══════════════════════════════════════════════════════════════════════════════
-- 6. recommendation_dismissals
--    account_id was UUID originally, later migration added reason/resurface_at.
--    Column was changed to TEXT in the recommendation_dismissals_reason migration.
-- ══════════════════════════════════════════════════════════════════════════════

DELETE FROM recommendation_dismissals
WHERE account_id::text NOT IN (SELECT id FROM accounts);

ALTER TABLE recommendation_dismissals
  ALTER COLUMN account_id TYPE text USING account_id::text;

ALTER TABLE recommendation_dismissals
  ADD CONSTRAINT fk_recommendation_dismissals_account
  FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;

-- ══════════════════════════════════════════════════════════════════════════════
-- 7. creator_events
--    account_id was UUID, migrated to TEXT in 20260222.
--    Has user_id FK to auth.users (CASCADE) but no account_id FK.
-- ══════════════════════════════════════════════════════════════════════════════

DELETE FROM creator_events
WHERE account_id NOT IN (SELECT id FROM accounts);

ALTER TABLE creator_events
  ADD CONSTRAINT fk_creator_events_account
  FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;

-- ══════════════════════════════════════════════════════════════════════════════
-- 8. quick_wins
--    Has user_id FK to profiles (CASCADE) but no account_id FK.
-- ══════════════════════════════════════════════════════════════════════════════

DELETE FROM quick_wins
WHERE account_id NOT IN (SELECT id FROM accounts);

ALTER TABLE quick_wins
  ADD CONSTRAINT fk_quick_wins_account
  FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;

-- ══════════════════════════════════════════════════════════════════════════════
-- 9. style_bibles
--    account_id is nullable TEXT, no FK. Only cascade when non-null.
-- ══════════════════════════════════════════════════════════════════════════════

DELETE FROM style_bibles
WHERE account_id IS NOT NULL
  AND account_id NOT IN (SELECT id FROM accounts);

ALTER TABLE style_bibles
  ADD CONSTRAINT fk_style_bibles_account
  FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE SET NULL;

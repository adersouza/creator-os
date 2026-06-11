-- Applied via schema reconciliation 2026-03-07
-- Adds FK CASCADE to 9 tables that had no account_id foreign key,
-- preventing orphaned rows when accounts are disconnected.
-- Cleaned 839 orphaned rows (807 account_analytics, 29 post_metric_history, 3 recommendation_dismissals).

DELETE FROM account_analytics WHERE account_id NOT IN (SELECT id FROM accounts);
DO $$ BEGIN
  ALTER TABLE account_analytics ADD CONSTRAINT fk_account_analytics_account
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  ALTER TABLE account_daily_summary ADD CONSTRAINT fk_account_daily_summary_account
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DELETE FROM post_metric_history WHERE account_id NOT IN (SELECT id FROM accounts);
DO $$ BEGIN
  ALTER TABLE post_metric_history ADD CONSTRAINT fk_post_metric_history_account
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  ALTER TABLE rate_limit_tracking ADD CONSTRAINT fk_rate_limit_tracking_account
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  ALTER TABLE recommendation_baselines ADD CONSTRAINT fk_recommendation_baselines_account
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DELETE FROM recommendation_dismissals WHERE account_id NOT IN (SELECT id FROM accounts);
DO $$ BEGIN
  ALTER TABLE recommendation_dismissals ADD CONSTRAINT fk_recommendation_dismissals_account
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  ALTER TABLE creator_events ADD CONSTRAINT fk_creator_events_account
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  ALTER TABLE quick_wins ADD CONSTRAINT fk_quick_wins_account
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  ALTER TABLE style_bibles ADD CONSTRAINT fk_style_bibles_account
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE SET NULL;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

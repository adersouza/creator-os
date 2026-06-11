-- ROLLBACK for 20260307100000_add_cascade_fks_orphaned_tables.sql
-- Run this manually if the migration needs to be reversed.
-- NOTE: This does NOT restore deleted orphaned rows (they were garbage data).

ALTER TABLE account_analytics       DROP CONSTRAINT IF EXISTS fk_account_analytics_account;
ALTER TABLE account_daily_summary   DROP CONSTRAINT IF EXISTS fk_account_daily_summary_account;
ALTER TABLE post_metric_history     DROP CONSTRAINT IF EXISTS fk_post_metric_history_account;
ALTER TABLE rate_limit_tracking     DROP CONSTRAINT IF EXISTS fk_rate_limit_tracking_account;
ALTER TABLE recommendation_baselines DROP CONSTRAINT IF EXISTS fk_recommendation_baselines_account;
ALTER TABLE recommendation_dismissals DROP CONSTRAINT IF EXISTS fk_recommendation_dismissals_account;
ALTER TABLE creator_events          DROP CONSTRAINT IF EXISTS fk_creator_events_account;
ALTER TABLE quick_wins              DROP CONSTRAINT IF EXISTS fk_quick_wins_account;
ALTER TABLE style_bibles            DROP CONSTRAINT IF EXISTS fk_style_bibles_account;

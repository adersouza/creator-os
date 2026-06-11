-- Backfilled from DB migration history
ALTER TABLE account_analytics DROP CONSTRAINT IF EXISTS account_analytics_account_id_date_key;

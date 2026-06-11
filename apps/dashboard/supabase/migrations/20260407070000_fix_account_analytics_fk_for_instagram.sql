-- account_analytics stores data for both Threads (accounts table) and Instagram
-- (instagram_accounts table). The FK only references accounts(id), so every IG
-- analytics upsert fails silently. Drop the FK since account_id can come from
-- either table. The ON DELETE CASCADE cleanup is handled by application code
-- (GDPR deletion cascade) and platform-specific sync logic.
ALTER TABLE account_analytics DROP CONSTRAINT IF EXISTS fk_account_analytics_account;

-- Also drop the original schema.sql FK if it exists under a different name
ALTER TABLE account_analytics DROP CONSTRAINT IF EXISTS account_analytics_account_id_fkey;

-- Same issue on account_metrics_history
ALTER TABLE account_metrics_history DROP CONSTRAINT IF EXISTS fk_account_metrics_history_account;
ALTER TABLE account_metrics_history DROP CONSTRAINT IF EXISTS account_metrics_history_account_id_fkey;

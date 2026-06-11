-- Backfilled from DB migration history
DELETE FROM account_analytics a USING account_analytics b
WHERE a.account_id = b.account_id AND a.date = b.date AND a.id < b.id;
DO $$ BEGIN
  ALTER TABLE account_analytics ADD CONSTRAINT uq_account_analytics_account_date UNIQUE (account_id, date);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

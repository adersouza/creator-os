-- Make account_health_snapshots explicitly polymorphic across account tables.
-- The runtime schema had drifted into an accidental FK to accounts(id), which
-- prevented instagram_accounts snapshots from being stored safely.

ALTER TABLE public.account_health_snapshots
  ADD COLUMN IF NOT EXISTS account_table text;

UPDATE public.account_health_snapshots
SET account_table = CASE
  WHEN platform = 'instagram' THEN 'instagram_accounts'
  ELSE 'accounts'
END
WHERE account_table IS NULL;

ALTER TABLE public.account_health_snapshots
  ALTER COLUMN account_table SET DEFAULT 'accounts',
  ALTER COLUMN account_table SET NOT NULL;

DO $$ BEGIN
  ALTER TABLE public.account_health_snapshots
    DROP CONSTRAINT IF EXISTS fk_account_health_snapshots_account;
EXCEPTION WHEN undefined_table THEN
  NULL;
END $$;

DO $$ BEGIN
  ALTER TABLE public.account_health_snapshots
    DROP CONSTRAINT IF EXISTS account_health_snapshots_account_id_fkey;
EXCEPTION WHEN undefined_table THEN
  NULL;
END $$;

ALTER TABLE public.account_health_snapshots
  DROP CONSTRAINT IF EXISTS account_health_snapshots_user_id_account_id_period_days_key;

ALTER TABLE public.account_health_snapshots
  DROP CONSTRAINT IF EXISTS account_health_snapshots_account_table_check;

ALTER TABLE public.account_health_snapshots
  ADD CONSTRAINT account_health_snapshots_account_table_check
  CHECK (account_table IN ('accounts', 'instagram_accounts'));

ALTER TABLE public.account_health_snapshots
  ADD CONSTRAINT account_health_snapshots_user_account_scope_period_key
  UNIQUE (user_id, account_table, account_id, period_days);

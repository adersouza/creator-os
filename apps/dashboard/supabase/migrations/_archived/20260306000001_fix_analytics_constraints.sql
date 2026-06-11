-- Fix: account_analytics upsert was inserting duplicates because no UNIQUE constraint existed.
-- The code uses onConflict: "account_id,date" but only a regular index existed.

-- Step 1: Deduplicate existing rows (keep the latest id per account_id+date)
DELETE FROM account_analytics a
USING account_analytics b
WHERE a.account_id = b.account_id
  AND a.date = b.date
  AND a.id < b.id;

-- Step 2: Add UNIQUE constraint
ALTER TABLE account_analytics
  ADD CONSTRAINT uq_account_analytics_account_date UNIQUE (account_id, date);

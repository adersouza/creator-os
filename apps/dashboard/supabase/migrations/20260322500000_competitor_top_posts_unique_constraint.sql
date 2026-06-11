-- Fix: competitor_top_posts upsert has been silently failing since day 1
-- because .upsert({ onConflict: "threads_post_id" }) requires a UNIQUE constraint
-- that never existed. PostgreSQL rejects ON CONFLICT without a matching constraint.
-- This migration deduplicates existing rows and adds the constraint.

-- Step 1: Delete duplicates, keeping the row with the most recent scraped_at
DELETE FROM competitor_top_posts a
USING competitor_top_posts b
WHERE a.threads_post_id = b.threads_post_id
  AND a.threads_post_id IS NOT NULL
  AND a.id <> b.id
  AND (a.scraped_at < b.scraped_at OR (a.scraped_at = b.scraped_at AND a.id < b.id));

-- Step 2: Add UNIQUE constraint (partial — NULLs are allowed and won't conflict)
CREATE UNIQUE INDEX IF NOT EXISTS idx_competitor_top_posts_threads_post_id
  ON competitor_top_posts (threads_post_id)
  WHERE threads_post_id IS NOT NULL;

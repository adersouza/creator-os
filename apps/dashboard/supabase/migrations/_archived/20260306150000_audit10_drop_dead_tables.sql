-- Audit #10 Finding 5: Drop 5 truly dead tables (zero code references)
-- These tables exist only in migrations/types — no .from() calls, no queries, no API routes.
-- Confirmed dead in Audit #2 (Finding 1).

DROP TABLE IF EXISTS product_tags CASCADE;
DROP TABLE IF EXISTS queue_slots CASCADE;
DROP TABLE IF EXISTS trial_emails CASCADE;
DROP TABLE IF EXISTS user_goals CASCADE;
DROP TABLE IF EXISTS goal_history_snapshots CASCADE;

-- Fix: Add missing created_at column to ig_pending_containers
-- The column was defined in the original CREATE TABLE migration (20260206000005)
-- and the combined migration (20260207000001), but is missing in production.
-- The ig-container-publisher cron orders by created_at, causing persistent failures.

ALTER TABLE ig_pending_containers
  ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();

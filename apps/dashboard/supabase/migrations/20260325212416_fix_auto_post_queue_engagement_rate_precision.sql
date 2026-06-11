-- Reconstructed from schema_migrations on prod (remote-only).
-- version: 20260325212416
-- applied-by: fix_auto_post_queue_engagement_rate_precision migration row

-- Fix DECIMAL(5,4) overflow on auto_post_queue.engagement_rate
-- DECIMAL(5,4) maxes at 9.9999 — too small for small/new accounts with >10% engagement
-- This is the last remaining DECIMAL(5,4) engagement_rate column in the database

ALTER TABLE public.auto_post_queue
  ALTER COLUMN engagement_rate TYPE DECIMAL(8,4);

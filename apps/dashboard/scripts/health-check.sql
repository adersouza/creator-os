-- AUTOPOSTER HEALTH CHECK — run after every deploy
-- Copy-paste into Supabase SQL Editor or run via MCP execute_sql
--
-- Green = all groups have pending > 0, published_3h > 0, last_publish < 30 min ago
-- Yellow = high rejection rate (>50%), low pending (<3)
-- Red = 0 pending, 0 published, last_publish > 1h ago

SELECT
  ag.name as "group",

  -- Queue depth
  (SELECT COUNT(*) FROM auto_post_queue q WHERE q.group_id = ag.id AND q.status = 'pending') as pending,
  (SELECT COUNT(*) FROM auto_post_queue q WHERE q.group_id = ag.id AND q.status = 'published' AND q.posted_at > NOW() - interval '3 hours') as published_3h,
  (SELECT COUNT(*) FROM auto_post_queue q WHERE q.group_id = ag.id AND q.status = 'rejected' AND q.created_at > NOW() - interval '3 hours') as rejected_3h,

  -- Last publish + fill times
  (SELECT MAX(q.posted_at) FROM auto_post_queue q WHERE q.group_id = ag.id AND q.status = 'published') as last_publish,
  (SELECT MAX(q.created_at) FROM auto_post_queue q WHERE q.group_id = ag.id AND q.status = 'pending') as last_fill,

  -- Group state
  gs.posts_today,
  gs.last_reset_date,

  -- Config
  gc.enabled as config_on,
  gc.active_hours_start as hrs_start,
  gc.active_hours_end as hrs_end,

  -- Active accounts
  (SELECT COUNT(*) FROM accounts a WHERE a.group_id = ag.id AND a.is_active = true) as active_accounts,

  -- Media library size
  (SELECT COUNT(*) FROM media m WHERE m.group_id = ag.id) as media_count

FROM account_groups ag
JOIN auto_post_group_config gc ON gc.group_id = ag.id AND gc.enabled = true
LEFT JOIN auto_post_group_state gs ON gs.group_id = ag.id
ORDER BY ag.name;

-- Also check workspace-level config
SELECT
  is_enabled, group_mode_enabled, enable_ai_queue_fill,
  ai_generations_today, ai_daily_generation_limit, ai_last_generation_date,
  content_filter_min_length, content_filter_max_length, content_filter_max_emojis,
  ai_provider
FROM auto_post_config;

-- ============================================================================
-- FIX: Unflag accounts killed by Meta's generic "An unknown error" (code=1)
-- Run this if Discord shows OAuthException failures with "An unknown error has occurred"
-- These are transient Meta 500s, NOT dead tokens.
-- ============================================================================
-- Step 1: Check which accounts are flagged (DRY RUN)
SELECT id, username, needs_reauth, is_active, updated_at
FROM accounts
WHERE needs_reauth = true
ORDER BY updated_at DESC;

-- Step 2: Unflag them (UNCOMMENT to run)
-- UPDATE accounts
-- SET needs_reauth = false, is_active = true, updated_at = NOW()
-- WHERE needs_reauth = true AND token_expires_at > NOW();

-- ============================================================================
-- CONFIG DRIFT DETECTION — DB column defaults vs expected code defaults
-- Any row returned has a NULL where the code expects a non-NULL default.
-- Fix: run the backfill UPDATE below or apply the migration.
-- ============================================================================
SELECT
  gc.group_id,
  ag.name as group_name,
  CASE WHEN gc.crossreshare_to_ig IS NULL THEN 'NULL (expect false)' END as crossreshare_to_ig,
  CASE WHEN gc.crossreshare_to_ig_dark_mode IS NULL THEN 'NULL (expect false)' END as crossreshare_to_ig_dark_mode,
  CASE WHEN gc.round_robin_enabled IS NULL THEN 'NULL (expect true)' END as round_robin_enabled,
  CASE WHEN gc.media_attachment_chance IS NULL THEN 'NULL (expect 0)' END as media_attachment_chance,
  CASE WHEN gc.media_source IS NULL THEN 'NULL (expect global)' END as media_source,
  CASE WHEN gc.require_approval IS NULL THEN 'NULL (expect false)' END as require_approval
FROM auto_post_group_config gc
JOIN account_groups ag ON ag.id = gc.group_id
WHERE gc.crossreshare_to_ig IS NULL
   OR gc.crossreshare_to_ig_dark_mode IS NULL
   OR gc.round_robin_enabled IS NULL
   OR gc.media_attachment_chance IS NULL
   OR gc.media_source IS NULL
   OR gc.require_approval IS NULL;

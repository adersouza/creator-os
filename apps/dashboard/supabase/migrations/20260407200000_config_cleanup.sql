-- Config Cleanup Migration
-- Drops dead columns, deletes empty disabled groups, cleans posting_times JSONB

-- ============================================================================
-- 1. Drop dead columns from auto_post_config
-- ============================================================================
ALTER TABLE auto_post_config
  DROP COLUMN IF EXISTS content_sources,
  DROP COLUMN IF EXISTS ai_settings,
  DROP COLUMN IF EXISTS posts_per_day,
  DROP COLUMN IF EXISTS account_rotation;

-- ============================================================================
-- 2. Drop self_reply_ratio from auto_post_group_config (feature removed)
-- ============================================================================
ALTER TABLE auto_post_group_config
  DROP COLUMN IF EXISTS self_reply_ratio;

-- ============================================================================
-- 3. Delete 4 empty groups (0 accounts) — clean from all referencing tables
-- ============================================================================
-- Groups to delete:
--   241afb59-4f71-4ae8-bece-29a3128380f9  Larissa -- Hot Takes PM (disabled, 0 accts)
--   26eceb55-e870-44c9-b0a9-e3aa6c51a72e  Lola -- Feeders AM       (disabled, 0 accts)
--   836fcb42-7220-41fd-bff6-1a7314eee9f4  Lola -- Feeders PM       (disabled, 0 accts)
--   SHXYMSNFbswbsJT0wUMA                  Stacey (parent)          (enabled,  0 accts)

DO $$
DECLARE
  dead_groups TEXT[] := ARRAY[
    '241afb59-4f71-4ae8-bece-29a3128380f9',
    '26eceb55-e870-44c9-b0a9-e3aa6c51a72e',
    '836fcb42-7220-41fd-bff6-1a7314eee9f4',
    'SHXYMSNFbswbsJT0wUMA'
  ];
BEGIN
  -- Child tables first
  IF to_regclass('public.auto_post_queue') IS NOT NULL THEN
    DELETE FROM auto_post_queue WHERE group_id = ANY(dead_groups);
  END IF;
  IF to_regclass('public.auto_post_group_state') IS NOT NULL THEN
    DELETE FROM auto_post_group_state WHERE group_id = ANY(dead_groups);
  END IF;
  IF to_regclass('public.account_autoposter_state') IS NOT NULL THEN
    DELETE FROM account_autoposter_state WHERE group_id = ANY(dead_groups);
  END IF;
  IF to_regclass('public.queue_fill_log') IS NOT NULL THEN
    DELETE FROM queue_fill_log WHERE group_id = ANY(dead_groups);
  END IF;
  IF to_regclass('public.auto_post_account_overrides') IS NOT NULL THEN
    DELETE FROM auto_post_account_overrides WHERE group_id = ANY(dead_groups);
  END IF;
  IF to_regclass('public.auto_post_group_config') IS NOT NULL THEN
    DELETE FROM auto_post_group_config WHERE group_id = ANY(dead_groups);
  END IF;
  -- Parent group definitions
  IF to_regclass('public.account_groups') IS NOT NULL THEN
    DELETE FROM account_groups WHERE id = ANY(dead_groups);
  END IF;
END $$;

-- ============================================================================
-- 4. Remove "Stacey" parent from posting_times.selected_groups array
-- ============================================================================
UPDATE auto_post_config
SET posting_times = jsonb_set(
  posting_times,
  '{selected_groups}',
  (
    SELECT COALESCE(jsonb_agg(elem), '[]'::jsonb)
    FROM jsonb_array_elements(posting_times->'selected_groups') AS elem
    WHERE elem::text != '"SHXYMSNFbswbsJT0wUMA"'
  )
)
WHERE posting_times->'selected_groups' IS NOT NULL
  AND posting_times::text LIKE '%SHXYMSNFbswbsJT0wUMA%';

-- ============================================================================
-- 5. Clean dead keys from posting_times JSONB
-- ============================================================================
UPDATE auto_post_config
SET posting_times = posting_times
  - 'min_interval'
  - 'max_interval'
  - 'media_source'
  - 'enable_weekends'
  - 'performance_check_window'
  - 'active_hours_start'
  - 'active_hours_end'
WHERE posting_times IS NOT NULL;

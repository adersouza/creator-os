-- Fix autoposter schema integrity issues found in audit
-- 1. Add "publishing" to auto_post_queue.status CHECK constraint
-- 2. Add content_filter_min_length column to auto_post_config
-- 3. Ensure is_enabled column exists on auto_post_config

-- Add "publishing" status to auto_post_queue CHECK constraint
-- Drop and recreate because ALTER CONSTRAINT doesn't support adding values
DO $$
BEGIN
    -- Only modify if the constraint exists
    IF EXISTS (
        SELECT 1 FROM information_schema.check_constraints
        WHERE constraint_name = 'auto_post_queue_status_check'
    ) THEN
        ALTER TABLE auto_post_queue DROP CONSTRAINT auto_post_queue_status_check;
        ALTER TABLE auto_post_queue ADD CONSTRAINT auto_post_queue_status_check
            CHECK (status IN ('pending', 'processing', 'posted', 'published', 'failed', 'dead_letter', 'cancelled', 'rejected', 'queued', 'scheduled', 'publishing'));
    END IF;
END $$;

-- Add content_filter_min_length to auto_post_config (referenced in code, no prior migration)
ALTER TABLE auto_post_config ADD COLUMN IF NOT EXISTS content_filter_min_length INTEGER DEFAULT NULL;

-- Ensure is_enabled exists (may have been renamed from "enabled" via dashboard)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'auto_post_config' AND column_name = 'is_enabled'
    ) THEN
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'auto_post_config' AND column_name = 'enabled'
        ) THEN
            ALTER TABLE auto_post_config RENAME COLUMN enabled TO is_enabled;
        ELSE
            ALTER TABLE auto_post_config ADD COLUMN is_enabled BOOLEAN DEFAULT false;
        END IF;
    END IF;
END $$;

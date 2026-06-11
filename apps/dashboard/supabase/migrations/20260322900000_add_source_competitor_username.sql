-- Track which competitor each adapted/direct post came from
-- Visible in get_auto_post_queue so operators can audit the pipeline

ALTER TABLE auto_post_queue
ADD COLUMN IF NOT EXISTS source_competitor_username TEXT;

-- Expand sync_jobs to support all sync types
ALTER TABLE sync_jobs DROP CONSTRAINT IF EXISTS sync_jobs_job_type_check;

ALTER TABLE sync_jobs
ADD CONSTRAINT sync_jobs_job_type_check
CHECK (job_type IN ('analytics', 'replies', 'competitors', 'reply-metrics', 'engagement', 'mentions'));

-- Add competitor-specific columns
ALTER TABLE sync_jobs
ADD COLUMN IF NOT EXISTS competitors_synced INTEGER DEFAULT 0;

-- Add mentions-specific columns
ALTER TABLE sync_jobs
ADD COLUMN IF NOT EXISTS mentions_found INTEGER DEFAULT 0;

-- Add engagement-specific columns
ALTER TABLE sync_jobs
ADD COLUMN IF NOT EXISTS engagement_updated INTEGER DEFAULT 0;

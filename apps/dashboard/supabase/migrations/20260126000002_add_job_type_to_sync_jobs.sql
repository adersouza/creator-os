-- Add job_type column to sync_jobs to distinguish between analytics and reply syncs
ALTER TABLE sync_jobs
ADD COLUMN IF NOT EXISTS job_type TEXT NOT NULL DEFAULT 'analytics'
CHECK (job_type IN ('analytics', 'replies'));

-- Add index for job_type filtering
CREATE INDEX IF NOT EXISTS idx_sync_jobs_job_type ON sync_jobs(job_type);

-- Add reply-specific columns
ALTER TABLE sync_jobs
ADD COLUMN IF NOT EXISTS posts_processed INTEGER DEFAULT 0;

ALTER TABLE sync_jobs
ADD COLUMN IF NOT EXISTS replies_found INTEGER DEFAULT 0;

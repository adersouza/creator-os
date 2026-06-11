-- Add quotes_count column to post_metric_history for Threads quote tracking.
-- Quotes are a strong virality signal that was previously omitted from historical snapshots.
ALTER TABLE post_metric_history ADD COLUMN IF NOT EXISTS quotes_count INTEGER DEFAULT 0;

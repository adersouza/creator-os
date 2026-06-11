-- Add total_clicks column to account_analytics for Threads link click tracking.
-- Threads user-level insights return clicks via link_total_values response format.
ALTER TABLE account_analytics ADD COLUMN IF NOT EXISTS total_clicks INTEGER DEFAULT 0;

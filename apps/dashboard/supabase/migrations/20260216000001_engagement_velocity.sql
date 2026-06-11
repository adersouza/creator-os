-- Migration: Add engagement velocity tracking for smarter auto-poster
-- Enables real-time engagement velocity monitoring and trend-based pause/prioritize

-- Add velocity columns to auto_post_queue
ALTER TABLE public.auto_post_queue
  ADD COLUMN IF NOT EXISTS engagement_velocity FLOAT,
  ADD COLUMN IF NOT EXISTS velocity_trend TEXT DEFAULT 'unknown'
    CHECK (velocity_trend IN ('accelerating', 'stable', 'declining', 'unknown')),
  ADD COLUMN IF NOT EXISTS last_velocity_check TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_auto_post_queue_velocity
  ON public.auto_post_queue(workspace_id, status, posted_at)
  WHERE status = 'posted' AND engagement_velocity IS NOT NULL;

-- Engagement snapshots for time-series velocity calculation
CREATE TABLE IF NOT EXISTS auto_post_engagement_snapshots (
  id TEXT DEFAULT gen_random_uuid()::TEXT PRIMARY KEY,
  queue_item_id UUID NOT NULL REFERENCES auto_post_queue(id) ON DELETE CASCADE,
  snapshot_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  hours_since_post FLOAT,
  views_count INTEGER DEFAULT 0,
  likes_count INTEGER DEFAULT 0,
  replies_count INTEGER DEFAULT 0,
  reposts_count INTEGER DEFAULT 0,
  cumulative_engagement FLOAT DEFAULT 0,
  engagement_velocity FLOAT DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_engagement_snapshots_queue_item
  ON public.auto_post_engagement_snapshots(queue_item_id, snapshot_at DESC);

-- Add velocity-based config options to auto_post_config
ALTER TABLE public.auto_post_config
  ADD COLUMN IF NOT EXISTS enable_velocity_monitoring BOOLEAN DEFAULT false,
  ADD COLUMN IF NOT EXISTS velocity_acceleration_threshold FLOAT DEFAULT 5.0,
  ADD COLUMN IF NOT EXISTS velocity_decline_threshold FLOAT DEFAULT 0.5,
  ADD COLUMN IF NOT EXISTS pause_on_declining_velocity BOOLEAN DEFAULT false,
  ADD COLUMN IF NOT EXISTS boost_on_viral BOOLEAN DEFAULT false,
  ADD COLUMN IF NOT EXISTS viral_interval_reduction_pct INTEGER DEFAULT 50;

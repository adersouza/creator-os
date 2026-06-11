-- Analytics capture fidelity: follower-reach breakdown + post-attributed follows.
--
-- account_analytics.ig_non_follower_reach_pct was already being stored, but the
-- absolute counts (follower_reach, non_follower_reach) were computed from the
-- Graph API and thrown away. The pct-only shape cannot render a stacked area
-- over time; adding the absolute columns unblocks the follower-vs-non-follower
-- reach chart in Wave 1 of the Analytics roadmap.
--
-- posts.ig_follows_count captures Meta's native post-attributed follows signal
-- (returned by /media/insights when 'follows' is in the metric list). This
-- replaces daily-diff inference as the ground truth for follower-attribution.

ALTER TABLE account_analytics
  ADD COLUMN IF NOT EXISTS ig_follower_reach INTEGER DEFAULT 0,
  ADD COLUMN IF NOT EXISTS ig_non_follower_reach INTEGER DEFAULT 0;

ALTER TABLE posts
  ADD COLUMN IF NOT EXISTS ig_follows_count INTEGER DEFAULT 0;

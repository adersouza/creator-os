-- Phase 1: Single source of truth for account-level autoposter state
-- Replaces 9 Redis key patterns with one DB table

-- Status enum for account autoposter state
CREATE TYPE account_autoposter_status AS ENUM (
  'active',
  'warming_silent',
  'warming_limited',
  'viral_suppress',
  'flop_delay',
  'view_cooldown',
  'suppressed',
  'suppressed_probe',
  'shadowban_throttle',
  'inactive'
);

CREATE TABLE account_autoposter_state (
  account_id TEXT PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
  group_id TEXT NOT NULL,
  workspace_id TEXT NOT NULL,

  -- Current status
  status account_autoposter_status NOT NULL DEFAULT 'active',
  status_reason TEXT,                  -- Human-readable explanation
  blocked_until TIMESTAMPTZ,           -- NULL = not blocked

  -- Counters
  flop_proven_remaining INT DEFAULT 0, -- Posts left in flop recovery sequence
  probe_posts_remaining INT DEFAULT 0, -- Probe posts left before re-evaluation
  warming_posts_today INT DEFAULT 0,   -- Posts published today during warming

  -- Performance snapshot (refreshed by state evaluator cron)
  last_14d_avg_views NUMERIC,
  median_30d_views NUMERIC,
  max_30d_views INT,
  pct_under_5_views NUMERIC,          -- Percentage of last 30d posts with <5 views

  -- Skip tracking
  last_skip_reason TEXT,
  last_skip_at TIMESTAMPTZ,

  -- Timestamps
  evaluated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for common query patterns
CREATE INDEX idx_aas_group_id ON account_autoposter_state(group_id);
CREATE INDEX idx_aas_workspace_id ON account_autoposter_state(workspace_id);
CREATE INDEX idx_aas_status ON account_autoposter_state(status);
CREATE INDEX idx_aas_blocked_until ON account_autoposter_state(blocked_until) WHERE blocked_until IS NOT NULL;

-- RLS: service_role only (no user access)
ALTER TABLE account_autoposter_state ENABLE ROW LEVEL SECURITY;

-- No trigger for updated_at — handled in application code (matches codebase convention)

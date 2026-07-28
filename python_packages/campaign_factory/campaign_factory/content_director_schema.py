"""SQLite schema fragment owned by the supervised Content Director domain."""

from __future__ import annotations

CONTENT_DIRECTOR_SCHEMA = """
CREATE TABLE IF NOT EXISTS creative_plan_versions (
  id TEXT PRIMARY KEY,
  creative_plan_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  creator TEXT NOT NULL,
  identity_profile TEXT NOT NULL,
  horizon_start TEXT NOT NULL,
  horizon_end TEXT NOT NULL,
  account_scope_json TEXT NOT NULL DEFAULT '[]',
  timezone TEXT NOT NULL,
  objective TEXT NOT NULL,
  requested_output_count INTEGER NOT NULL,
  content_mix_policy_json TEXT NOT NULL DEFAULT '{}',
  exploration_policy_json TEXT NOT NULL DEFAULT '{}',
  estimated_spend_json TEXT NOT NULL DEFAULT '{}',
  signed_spend_ceiling REAL,
  creation_window_json TEXT NOT NULL DEFAULT '{}',
  publication_window_json TEXT NOT NULL DEFAULT '{}',
  autonomy_mode TEXT NOT NULL DEFAULT 'SUPERVISED',
  status TEXT NOT NULL DEFAULT 'DRAFT',
  input_fingerprint TEXT NOT NULL,
  previous_plan_version_id TEXT,
  decision_receipt_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(creative_plan_id, version),
  UNIQUE(input_fingerprint),
  FOREIGN KEY(creative_plan_id) REFERENCES creative_plans(id) ON UPDATE CASCADE,
  FOREIGN KEY(previous_plan_version_id) REFERENCES creative_plan_versions(id) ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS creative_plan_items (
  id TEXT PRIMARY KEY,
  plan_version_id TEXT NOT NULL,
  item_index INTEGER NOT NULL,
  creator TEXT NOT NULL,
  identity_profile TEXT NOT NULL,
  target_account TEXT NOT NULL,
  content_intent TEXT NOT NULL,
  source_asset_id TEXT,
  source_candidate_ids_json TEXT NOT NULL DEFAULT '[]',
  source_ranking_json TEXT NOT NULL DEFAULT '{}',
  reference_pattern_id TEXT,
  pattern_family TEXT NOT NULL,
  pattern_ranking_json TEXT NOT NULL DEFAULT '{}',
  prompt_text TEXT NOT NULL,
  desired_duration_seconds REAL NOT NULL,
  audio_policy TEXT NOT NULL,
  audio_profile_json TEXT NOT NULL DEFAULT '{}',
  proposed_window_json TEXT NOT NULL DEFAULT '{}',
  experiment_id TEXT,
  experiment_variant TEXT,
  exploration_class TEXT NOT NULL,
  priority INTEGER NOT NULL,
  dependencies_json TEXT NOT NULL DEFAULT '[]',
  estimated_cost_json TEXT NOT NULL DEFAULT '{}',
  execution_state TEXT NOT NULL DEFAULT 'DRAFT',
  generation_identity_json TEXT NOT NULL DEFAULT '{}',
  review_identity_json TEXT NOT NULL DEFAULT '{}',
  export_identity_json TEXT NOT NULL DEFAULT '{}',
  publication_identity_json TEXT NOT NULL DEFAULT '{}',
  metric_cohort_identity_json TEXT NOT NULL DEFAULT '{}',
  learning_outcome_identity_json TEXT NOT NULL DEFAULT '{}',
  decision_receipt_json TEXT NOT NULL DEFAULT '{}',
  blocking_reasons_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(plan_version_id, item_index),
  FOREIGN KEY(plan_version_id) REFERENCES creative_plan_versions(id) ON UPDATE CASCADE,
  FOREIGN KEY(source_asset_id) REFERENCES source_assets(id) ON UPDATE CASCADE,
  FOREIGN KEY(reference_pattern_id) REFERENCES reference_patterns(id) ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS creative_plan_item_events (
  id TEXT PRIMARY KEY,
  plan_item_id TEXT NOT NULL,
  from_state TEXT,
  to_state TEXT NOT NULL,
  event_type TEXT NOT NULL,
  actor TEXT NOT NULL,
  reason TEXT NOT NULL,
  receipt_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  FOREIGN KEY(plan_item_id) REFERENCES creative_plan_items(id) ON UPDATE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_creative_plan_versions_scope
  ON creative_plan_versions(creator, status, horizon_start, horizon_end);
CREATE INDEX IF NOT EXISTS idx_creative_plan_versions_account
  ON creative_plan_versions(status, updated_at);
CREATE INDEX IF NOT EXISTS idx_creative_plan_items_plan_state
  ON creative_plan_items(plan_version_id, execution_state, priority);
CREATE INDEX IF NOT EXISTS idx_creative_plan_items_scope
  ON creative_plan_items(creator, target_account, content_intent, execution_state);
CREATE INDEX IF NOT EXISTS idx_creative_plan_items_source
  ON creative_plan_items(source_asset_id, execution_state);

CREATE TABLE IF NOT EXISTS creative_plan_experiments (
  id TEXT PRIMARY KEY,
  plan_version_id TEXT NOT NULL,
  creator TEXT NOT NULL,
  account_scope_json TEXT NOT NULL DEFAULT '[]',
  content_intent TEXT NOT NULL,
  hypothesis TEXT NOT NULL,
  controlled_variables_json TEXT NOT NULL DEFAULT '[]',
  changed_variable TEXT NOT NULL,
  variants_json TEXT NOT NULL DEFAULT '[]',
  assignment_method TEXT NOT NULL,
  deterministic_seed INTEGER NOT NULL,
  publication_windows_json TEXT NOT NULL DEFAULT '[]',
  required_observation_cohort TEXT NOT NULL,
  minimum_sample_warning TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'PROPOSED',
  outcome_links_json TEXT NOT NULL DEFAULT '[]',
  interpretation_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(plan_version_id) REFERENCES creative_plan_versions(id) ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS creative_plan_metric_cohorts (
  id TEXT PRIMARY KEY,
  plan_item_id TEXT NOT NULL,
  observation_bucket TEXT NOT NULL,
  expected_earliest_at TEXT NOT NULL,
  actual_observed_at TEXT,
  post_age_seconds INTEGER,
  observation_state TEXT NOT NULL DEFAULT 'MISSING',
  snapshot_id TEXT,
  learning_eligible INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(plan_item_id, observation_bucket),
  FOREIGN KEY(plan_item_id) REFERENCES creative_plan_items(id) ON UPDATE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_creative_plan_experiments_scope
  ON creative_plan_experiments(creator, content_intent, status);
CREATE INDEX IF NOT EXISTS idx_creative_plan_metric_due
  ON creative_plan_metric_cohorts(observation_state, expected_earliest_at);
"""

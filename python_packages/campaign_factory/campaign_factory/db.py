from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from creator_os_core.sqlite import connect_sqlite
from creator_os_core.sqlite import ensure_columns as _ensure_columns

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS campaigns (
  id TEXT PRIMARY KEY,
  slug TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  platform TEXT NOT NULL DEFAULT 'instagram',
  root_path TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS models (
  id TEXT PRIMARY KEY,
  slug TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  notes TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS accounts (
  id TEXT PRIMARY KEY,
  handle TEXT NOT NULL,
  platform TEXT NOT NULL DEFAULT 'instagram',
  external_id TEXT,
  model_id TEXT,
  account_group_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(handle, platform),
  FOREIGN KEY(model_id) REFERENCES models(id)
);

CREATE TABLE IF NOT EXISTS source_assets (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  model_id TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  original_path TEXT NOT NULL,
  stored_path TEXT NOT NULL,
  filename TEXT NOT NULL,
  media_type TEXT NOT NULL DEFAULT 'video',
  content_surface TEXT NOT NULL DEFAULT 'reel',
  platform TEXT NOT NULL DEFAULT 'instagram',
  source_prompt TEXT,
  higgsfield_job_id TEXT,
  higgsfield_model TEXT,
  notes TEXT,
  account_ids_json TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'imported',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(campaign_id, content_hash),
  FOREIGN KEY(campaign_id) REFERENCES campaigns(id),
  FOREIGN KEY(model_id) REFERENCES models(id)
);

CREATE TABLE IF NOT EXISTS creative_plans (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  platform TEXT NOT NULL DEFAULT 'instagram',
  goal TEXT NOT NULL DEFAULT 'views_reach',
  target_account TEXT NOT NULL,
  daily_base_video_target INTEGER NOT NULL DEFAULT 10,
  style_lanes_json TEXT NOT NULL DEFAULT '[]',
  model_profile TEXT NOT NULL DEFAULT '',
  source_accounts_json TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'planned',
  linked_campaign_slug TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS creative_plan_events (
  id TEXT PRIMARY KEY,
  creative_plan_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'info',
  message TEXT NOT NULL DEFAULT '',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  FOREIGN KEY(creative_plan_id) REFERENCES creative_plans(id)
);

CREATE INDEX IF NOT EXISTS idx_creative_plans_status ON creative_plans(status, updated_at);

CREATE TABLE IF NOT EXISTS manager_decisions (
  id TEXT PRIMARY KEY,
  creator TEXT,
  account_id TEXT,
  rendered_asset_id TEXT,
  parent_asset_id TEXT,
  variant_id TEXT,
  content_surface TEXT,
  decision_type TEXT NOT NULL,
  reason TEXT NOT NULL,
  source_system TEXT NOT NULL,
  explanation TEXT NOT NULL DEFAULT '',
  context_snapshot_json TEXT NOT NULL DEFAULT '{}',
  decision_payload_json TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'previewed',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_manager_decisions_creator
  ON manager_decisions(creator, created_at);

CREATE INDEX IF NOT EXISTS idx_manager_decisions_account
  ON manager_decisions(account_id, created_at);

CREATE INDEX IF NOT EXISTS idx_manager_decisions_type
  ON manager_decisions(decision_type, reason, created_at);

CREATE INDEX IF NOT EXISTS idx_manager_decisions_surface
  ON manager_decisions(content_surface, created_at);

CREATE TABLE IF NOT EXISTS asset_rejection_evidence (
  id TEXT PRIMARY KEY,
  rendered_asset_id TEXT,
  source_asset_id TEXT,
  campaign_id TEXT,
  content_surface TEXT NOT NULL DEFAULT 'reel',
  failed_stage TEXT NOT NULL,
  failure_category TEXT NOT NULL,
  matched_text TEXT NOT NULL DEFAULT '',
  source_field TEXT NOT NULL DEFAULT '',
  policy_version TEXT NOT NULL,
  repairable INTEGER NOT NULL DEFAULT 1,
  evidence_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(rendered_asset_id, failed_stage, failure_category, matched_text, source_field, policy_version),
  FOREIGN KEY(rendered_asset_id) REFERENCES rendered_assets(id) ON UPDATE CASCADE,
  FOREIGN KEY(source_asset_id) REFERENCES source_assets(id) ON UPDATE CASCADE,
  FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON UPDATE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_asset_rejection_evidence_asset
  ON asset_rejection_evidence(rendered_asset_id, failed_stage, created_at);

CREATE INDEX IF NOT EXISTS idx_asset_rejection_evidence_category
  ON asset_rejection_evidence(failed_stage, failure_category, created_at);

CREATE TABLE IF NOT EXISTS render_jobs (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  source_asset_id TEXT NOT NULL,
  reel_clip_stem TEXT NOT NULL,
  hooks_json TEXT NOT NULL,
  recipes_json TEXT NOT NULL,
  caption_color TEXT,
  status TEXT NOT NULL DEFAULT 'prepared',
  reel_manifest_job_key TEXT,
  error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(campaign_id) REFERENCES campaigns(id),
  FOREIGN KEY(source_asset_id) REFERENCES source_assets(id)
);

CREATE TABLE IF NOT EXISTS rendered_assets (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  source_asset_id TEXT NOT NULL,
  parent_asset_id TEXT,
  concept_id TEXT,
  parent_reel_id TEXT,
  variant_family_id TEXT,
  variant_id TEXT,
  variant_index INTEGER,
  variant_operations_json TEXT NOT NULL DEFAULT '[]',
  render_job_id TEXT,
  content_hash TEXT NOT NULL,
  output_path TEXT NOT NULL,
  campaign_path TEXT NOT NULL,
  filename TEXT NOT NULL,
  media_type TEXT NOT NULL DEFAULT 'video',
  content_surface TEXT NOT NULL DEFAULT 'reel',
  caption TEXT,
  caption_hash TEXT,
  caption_bank TEXT,
  caption_banks_json TEXT NOT NULL DEFAULT '[]',
  creator_mix TEXT,
  creator_model TEXT,
  frame_type TEXT,
  length_class TEXT,
  format_class TEXT,
  caption_fit_version TEXT,
  suitability_decision TEXT,
  suitability_reason TEXT,
  source_clip TEXT,
  caption_outcome_context_json TEXT NOT NULL DEFAULT '{}',
  caption_generation_json TEXT NOT NULL DEFAULT '{}',
  recipe TEXT,
  target_ratio TEXT,
  story_asset_class TEXT,
  story_cta_type TEXT,
  story_cta_text TEXT,
  story_cta_target_url TEXT,
  story_intent TEXT,
  story_goal TEXT,
  story_style TEXT,
  snapchat_username TEXT,
  snapchat_display_name TEXT,
  snapchat_cta_text TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  origin_account_id TEXT,
  audit_status TEXT NOT NULL DEFAULT 'pending',
  review_state TEXT NOT NULL DEFAULT 'draft',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(campaign_id, content_hash),
  FOREIGN KEY(campaign_id) REFERENCES campaigns(id),
  FOREIGN KEY(source_asset_id) REFERENCES source_assets(id),
  FOREIGN KEY(parent_asset_id) REFERENCES rendered_assets(id),
  FOREIGN KEY(render_job_id) REFERENCES render_jobs(id)
);

CREATE TABLE IF NOT EXISTS concepts (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  creator TEXT,
  parent_reel_id TEXT NOT NULL UNIQUE,
  parent_asset_id TEXT NOT NULL,
  source_asset_id TEXT,
  source_fingerprint TEXT,
  content_fingerprint TEXT,
  caption_hash TEXT,
  audio_id TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(campaign_id, parent_asset_id),
  FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON UPDATE CASCADE,
  FOREIGN KEY(parent_asset_id) REFERENCES rendered_assets(id) ON UPDATE CASCADE,
  FOREIGN KEY(source_asset_id) REFERENCES source_assets(id) ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS variant_families (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  concept_id TEXT NOT NULL,
  parent_reel_id TEXT NOT NULL,
  parent_asset_id TEXT NOT NULL,
  caption_family_id TEXT,
  caption_version_id TEXT,
  source_asset_id TEXT,
  requested_count INTEGER NOT NULL DEFAULT 0,
  contentforge_run_id TEXT,
  contentforge_preset TEXT NOT NULL DEFAULT 'caption_safe',
  cooldown_days INTEGER NOT NULL DEFAULT 14,
  status TEXT NOT NULL DEFAULT 'planned',
  manifest_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON UPDATE CASCADE,
  FOREIGN KEY(concept_id) REFERENCES concepts(id) ON UPDATE CASCADE,
  FOREIGN KEY(parent_asset_id) REFERENCES rendered_assets(id) ON UPDATE CASCADE,
  FOREIGN KEY(source_asset_id) REFERENCES source_assets(id) ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS caption_families (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  concept_id TEXT NOT NULL,
  parent_reel_id TEXT NOT NULL,
  parent_asset_id TEXT NOT NULL,
  creator TEXT,
  requested_count INTEGER NOT NULL DEFAULT 0,
  style TEXT NOT NULL DEFAULT 'ig_short',
  status TEXT NOT NULL DEFAULT 'planned',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(parent_asset_id, style),
  FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON UPDATE CASCADE,
  FOREIGN KEY(concept_id) REFERENCES concepts(id) ON UPDATE CASCADE,
  FOREIGN KEY(parent_asset_id) REFERENCES rendered_assets(id) ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS caption_versions (
  id TEXT PRIMARY KEY,
  caption_family_id TEXT NOT NULL,
  campaign_id TEXT NOT NULL,
  concept_id TEXT NOT NULL,
  parent_reel_id TEXT NOT NULL,
  parent_asset_id TEXT NOT NULL,
  variant_family_id TEXT,
  caption_family_index INTEGER NOT NULL,
  burned_caption_text TEXT NOT NULL,
  burned_caption_hash TEXT NOT NULL,
  instagram_post_caption TEXT NOT NULL,
  instagram_post_caption_hash TEXT NOT NULL,
  caption_cta TEXT,
  hashtags_json TEXT NOT NULL DEFAULT '[]',
  post_caption_style TEXT NOT NULL DEFAULT 'short_natural',
  caption_angle TEXT NOT NULL,
  caption_source TEXT NOT NULL DEFAULT 'caption_family_plan',
  status TEXT NOT NULL DEFAULT 'planned',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(caption_family_id, caption_family_index),
  FOREIGN KEY(caption_family_id) REFERENCES caption_families(id) ON UPDATE CASCADE,
  FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON UPDATE CASCADE,
  FOREIGN KEY(concept_id) REFERENCES concepts(id) ON UPDATE CASCADE,
  FOREIGN KEY(parent_asset_id) REFERENCES rendered_assets(id) ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS variant_assets (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  concept_id TEXT NOT NULL,
  parent_reel_id TEXT NOT NULL,
  variant_family_id TEXT NOT NULL,
  variant_index INTEGER NOT NULL,
  parent_asset_id TEXT NOT NULL,
  caption_family_id TEXT,
  caption_version_id TEXT,
  variant_asset_id TEXT NOT NULL,
  source_asset_id TEXT,
  source_fingerprint TEXT,
  content_fingerprint TEXT,
  caption_hash TEXT,
  audio_id TEXT,
  content_surface TEXT NOT NULL DEFAULT 'reel',
  operations_json TEXT NOT NULL DEFAULT '[]',
  qc_status TEXT NOT NULL DEFAULT 'pending',
  contentforge_run_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(variant_family_id, variant_index),
  UNIQUE(variant_asset_id),
  FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON UPDATE CASCADE,
  FOREIGN KEY(concept_id) REFERENCES concepts(id) ON UPDATE CASCADE,
  FOREIGN KEY(variant_family_id) REFERENCES variant_families(id) ON UPDATE CASCADE,
  FOREIGN KEY(parent_asset_id) REFERENCES rendered_assets(id) ON UPDATE CASCADE,
  FOREIGN KEY(variant_asset_id) REFERENCES rendered_assets(id) ON UPDATE CASCADE,
  FOREIGN KEY(source_asset_id) REFERENCES source_assets(id) ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS variant_account_usage (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  concept_id TEXT,
  parent_reel_id TEXT,
  variant_family_id TEXT,
  variant_id TEXT,
  rendered_asset_id TEXT,
  post_id TEXT,
  account_id TEXT,
  instagram_account_id TEXT,
  usage_state TEXT NOT NULL DEFAULT 'planned',
  scheduled_for TEXT,
  published_at TEXT,
  metrics_eligible INTEGER NOT NULL DEFAULT 0,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(variant_id, instagram_account_id, post_id),
  FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON UPDATE CASCADE,
  FOREIGN KEY(rendered_asset_id) REFERENCES rendered_assets(id) ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS audit_reports (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  rendered_asset_id TEXT NOT NULL,
  contentforge_run_id TEXT,
  report_path TEXT NOT NULL,
  score INTEGER NOT NULL,
  status TEXT NOT NULL,
  layers_json TEXT NOT NULL DEFAULT '{}',
  verdicts_json TEXT NOT NULL DEFAULT '{}',
  overall_verdict TEXT,
  files_analyzed INTEGER NOT NULL DEFAULT 0,
  failed_checks_json TEXT NOT NULL DEFAULT '[]',
  warnings_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL,
  FOREIGN KEY(campaign_id) REFERENCES campaigns(id),
  FOREIGN KEY(rendered_asset_id) REFERENCES rendered_assets(id)
);

CREATE TABLE IF NOT EXISTS approval_decisions (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  rendered_asset_id TEXT NOT NULL,
  decision TEXT NOT NULL,
  notes TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY(campaign_id) REFERENCES campaigns(id),
  FOREIGN KEY(rendered_asset_id) REFERENCES rendered_assets(id)
);

CREATE TABLE IF NOT EXISTS kling_selection_receipts (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  batch_id TEXT NOT NULL,
  selected_rendered_asset_id TEXT NOT NULL,
  receipt_path TEXT NOT NULL,
  receipt_hash TEXT NOT NULL,
  ranking_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL,
  UNIQUE(campaign_id, batch_id),
  FOREIGN KEY(campaign_id) REFERENCES campaigns(id),
  FOREIGN KEY(selected_rendered_asset_id) REFERENCES rendered_assets(id)
);

CREATE TABLE IF NOT EXISTS threadsdash_exports (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  manifest_path TEXT NOT NULL,
  user_id TEXT NOT NULL,
  dry_run INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(campaign_id) REFERENCES campaigns(id)
);

CREATE TABLE IF NOT EXISTS performance_snapshots (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  rendered_asset_id TEXT,
  source_asset_id TEXT,
  content_hash TEXT,
  source_content_hash TEXT,
  concept_id TEXT,
  parent_reel_id TEXT,
  variant_family_id TEXT,
  variant_id TEXT,
  variant_index INTEGER,
  variant_operations_json TEXT NOT NULL DEFAULT '[]',
  audio_id TEXT,
  caption_hash TEXT,
  caption_family_id TEXT,
  caption_version_id TEXT,
  caption_angle TEXT,
  burned_caption_hash TEXT,
  instagram_post_caption_hash TEXT,
  caption_text TEXT,
  caption_bank TEXT,
  caption_banks_json TEXT NOT NULL DEFAULT '[]',
  creator_mix TEXT,
  creator_model TEXT,
  frame_type TEXT,
  length_class TEXT,
  format_class TEXT,
  caption_fit_version TEXT,
  suitability_decision TEXT,
  suitability_reason TEXT,
  source_clip TEXT,
  caption_outcome_context_json TEXT NOT NULL DEFAULT '{}',
  recipe TEXT,
  post_id TEXT NOT NULL,
  platform TEXT,
  content_surface TEXT NOT NULL DEFAULT 'reel',
  status TEXT,
  account_id TEXT,
  instagram_account_id TEXT,
  permalink TEXT,
  published_at TEXT,
  snapshot_at TEXT NOT NULL,
  views INTEGER,
  likes INTEGER,
  comments INTEGER,
  shares INTEGER,
  saves INTEGER,
  impressions INTEGER,
  reach INTEGER,
  watch_time_seconds REAL,
  metrics_eligible INTEGER NOT NULL DEFAULT 0,
  history_source TEXT,
  lineage_v2_valid INTEGER NOT NULL DEFAULT 0,
  raw_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  UNIQUE(post_id, snapshot_at),
  FOREIGN KEY(campaign_id) REFERENCES campaigns(id)
);

CREATE INDEX IF NOT EXISTS idx_performance_rendered_asset ON performance_snapshots(rendered_asset_id);
CREATE INDEX IF NOT EXISTS idx_performance_source_asset ON performance_snapshots(source_asset_id);
CREATE INDEX IF NOT EXISTS idx_performance_caption_hash ON performance_snapshots(caption_hash);
CREATE INDEX IF NOT EXISTS idx_performance_recipe ON performance_snapshots(recipe);

CREATE TABLE IF NOT EXISTS learning_fanout_ledger (
  post_id TEXT NOT NULL,
  snapshot_at TEXT NOT NULL,
  destination TEXT NOT NULL,
  snapshot_id TEXT,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK(status IN ('pending', 'done', 'superseded', 'failed_capped', 'retracted')),
  attempt_count INTEGER NOT NULL DEFAULT 0,
  source_hash TEXT NOT NULL,
  destination_record_id TEXT,
  scoring_version TEXT,
  baseline_provenance TEXT,
  last_error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(post_id, snapshot_at, destination)
);

CREATE INDEX IF NOT EXISTS idx_learning_fanout_status
  ON learning_fanout_ledger(destination, status, updated_at);
CREATE INDEX IF NOT EXISTS idx_learning_fanout_post
  ON learning_fanout_ledger(post_id, destination, snapshot_at);

CREATE TABLE IF NOT EXISTS tribev2_reel_scores (
  id TEXT PRIMARY KEY,
  rendered_asset_id TEXT,
  campaign_id TEXT,
  content_hash TEXT,
  model_id TEXT NOT NULL DEFAULT 'facebook/tribev2',
  model_mode TEXT NOT NULL DEFAULT 'audio_video_cpu',
  mean_abs_activation REAL NOT NULL DEFAULT 0,
  peak_abs_activation REAL NOT NULL DEFAULT 0,
  std_activation REAL NOT NULL DEFAULT 0,
  segments_count INTEGER NOT NULL DEFAULT 0,
  preds_shape_json TEXT NOT NULL DEFAULT '[]',
  metrics_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  FOREIGN KEY(campaign_id) REFERENCES campaigns(id)
);

CREATE INDEX IF NOT EXISTS idx_tribev2_rendered_asset ON tribev2_reel_scores(rendered_asset_id);
CREATE INDEX IF NOT EXISTS idx_tribev2_campaign ON tribev2_reel_scores(campaign_id);
CREATE INDEX IF NOT EXISTS idx_tribev2_content_hash ON tribev2_reel_scores(content_hash);

CREATE INDEX IF NOT EXISTS idx_concepts_campaign ON concepts(campaign_id, status);
CREATE INDEX IF NOT EXISTS idx_variant_families_concept ON variant_families(concept_id, status);
CREATE INDEX IF NOT EXISTS idx_variant_assets_family ON variant_assets(variant_family_id, variant_index);
CREATE INDEX IF NOT EXISTS idx_variant_usage_account ON variant_account_usage(instagram_account_id, variant_family_id, usage_state);

CREATE TABLE IF NOT EXISTS proof_runs (
  id TEXT PRIMARY KEY,
  campaign_id TEXT,
  rendered_asset_id TEXT NOT NULL,
  distribution_plan_id TEXT,
  threadsdash_draft_id TEXT,
  threadsdash_post_id TEXT,
  status TEXT NOT NULL DEFAULT 'started',
  current_state TEXT NOT NULL DEFAULT 'creative_approved',
  blocking_reason TEXT,
  root_cause TEXT,
  metrics_eligible INTEGER NOT NULL DEFAULT 0,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  started_at TEXT NOT NULL,
  completed_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON UPDATE CASCADE,
  FOREIGN KEY(rendered_asset_id) REFERENCES rendered_assets(id) ON UPDATE CASCADE,
  FOREIGN KEY(distribution_plan_id) REFERENCES distribution_plans(id) ON UPDATE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_proof_runs_campaign_asset ON proof_runs(campaign_id, rendered_asset_id, started_at);
CREATE INDEX IF NOT EXISTS idx_proof_runs_distribution_plan ON proof_runs(distribution_plan_id);
CREATE INDEX IF NOT EXISTS idx_proof_runs_status ON proof_runs(status, current_state);

CREATE TABLE IF NOT EXISTS quarantined_assets (
  id TEXT PRIMARY KEY,
  campaign_id TEXT,
  rendered_asset_id TEXT NOT NULL,
  distribution_plan_id TEXT,
  threadsdash_post_id TEXT,
  reason TEXT NOT NULL,
  root_cause TEXT,
  blocking_reason TEXT,
  excluded_from_metrics INTEGER NOT NULL DEFAULT 1,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  created_by TEXT,
  UNIQUE(rendered_asset_id),
  FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON UPDATE CASCADE,
  FOREIGN KEY(rendered_asset_id) REFERENCES rendered_assets(id) ON UPDATE CASCADE,
  FOREIGN KEY(distribution_plan_id) REFERENCES distribution_plans(id) ON UPDATE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_quarantined_assets_campaign ON quarantined_assets(campaign_id, created_at);
CREATE INDEX IF NOT EXISTS idx_quarantined_assets_reason ON quarantined_assets(reason, root_cause);

CREATE TABLE IF NOT EXISTS pipeline_jobs (
  id TEXT PRIMARY KEY,
  job_type TEXT NOT NULL,
  campaign_id TEXT,
  status TEXT NOT NULL DEFAULT 'queued',
  input_json TEXT NOT NULL DEFAULT '{}',
  result_json TEXT NOT NULL DEFAULT '{}',
  error TEXT,
  attempt_count INTEGER NOT NULL DEFAULT 0,
  started_at TEXT,
  finished_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(campaign_id) REFERENCES campaigns(id)
);

CREATE TABLE IF NOT EXISTS activity_events (
  id TEXT PRIMARY KEY,
  event_type TEXT NOT NULL,
  campaign_id TEXT,
  source_asset_id TEXT,
  rendered_asset_id TEXT,
  render_job_id TEXT,
  audit_report_id TEXT,
  threadsdash_export_id TEXT,
  pipeline_job_id TEXT,
  status TEXT NOT NULL DEFAULT 'info',
  message TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON UPDATE CASCADE,
  FOREIGN KEY(source_asset_id) REFERENCES source_assets(id) ON UPDATE CASCADE,
  FOREIGN KEY(rendered_asset_id) REFERENCES rendered_assets(id) ON UPDATE CASCADE,
  FOREIGN KEY(render_job_id) REFERENCES render_jobs(id) ON UPDATE CASCADE,
  FOREIGN KEY(audit_report_id) REFERENCES audit_reports(id) ON UPDATE CASCADE,
  FOREIGN KEY(threadsdash_export_id) REFERENCES threadsdash_exports(id) ON UPDATE CASCADE,
  FOREIGN KEY(pipeline_job_id) REFERENCES pipeline_jobs(id) ON UPDATE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_pipeline_jobs_campaign_created ON pipeline_jobs(campaign_id, created_at);
CREATE INDEX IF NOT EXISTS idx_pipeline_jobs_status ON pipeline_jobs(status);
CREATE INDEX IF NOT EXISTS idx_activity_events_campaign_created ON activity_events(campaign_id, created_at);
CREATE INDEX IF NOT EXISTS idx_activity_events_rendered_asset ON activity_events(rendered_asset_id, created_at);
CREATE INDEX IF NOT EXISTS idx_activity_events_type ON activity_events(event_type);

CREATE TABLE IF NOT EXISTS asset_account_assignments (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  rendered_asset_id TEXT NOT NULL,
  account_id TEXT,
  instagram_account_id TEXT,
  source_family_id TEXT,
  perceptual_fingerprint TEXT,
  perceptual_cluster_id TEXT,
  account_group_id TEXT,
  assignment_eligibility_json TEXT NOT NULL DEFAULT '{}',
  planned_window_start TEXT,
  planned_window_end TEXT,
  caption_hash TEXT,
  caption_text TEXT,
  caption_bank TEXT,
  caption_banks_json TEXT NOT NULL DEFAULT '[]',
  creator_mix TEXT,
  creator_model TEXT,
  frame_type TEXT,
  length_class TEXT,
  format_class TEXT,
  caption_fit_version TEXT,
  suitability_decision TEXT,
  suitability_reason TEXT,
  source_clip TEXT,
  caption_outcome_context_json TEXT NOT NULL DEFAULT '{}',
  notes TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON UPDATE CASCADE,
  FOREIGN KEY(rendered_asset_id) REFERENCES rendered_assets(id) ON UPDATE CASCADE,
  FOREIGN KEY(account_id) REFERENCES accounts(id) ON UPDATE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_asset_account_assignments_campaign ON asset_account_assignments(campaign_id, created_at);
CREATE INDEX IF NOT EXISTS idx_asset_account_assignments_rendered ON asset_account_assignments(rendered_asset_id);

CREATE TABLE IF NOT EXISTS asset_inventory_reservations (
  id TEXT PRIMARY KEY,
  asset_id TEXT NOT NULL,
  campaign_id TEXT NOT NULL,
  account_id TEXT,
  surface TEXT NOT NULL DEFAULT 'reel',
  reservation_id TEXT NOT NULL,
  reserved_by TEXT NOT NULL,
  reserved_at TEXT NOT NULL,
  expires_at TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  idempotency_key TEXT,
  source_family_id TEXT,
  perceptual_fingerprint TEXT,
  perceptual_cluster_id TEXT,
  account_group_id TEXT,
  reuse_cooldown_days INTEGER NOT NULL DEFAULT 14,
  override_reason TEXT,
  assignment_eligibility_json TEXT NOT NULL DEFAULT '{}',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(asset_id) REFERENCES rendered_assets(id) ON UPDATE CASCADE,
  FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON UPDATE CASCADE,
  FOREIGN KEY(account_id) REFERENCES accounts(id) ON UPDATE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_asset_inventory_reservations_asset
  ON asset_inventory_reservations(asset_id, status, reserved_at);

CREATE INDEX IF NOT EXISTS idx_asset_inventory_reservations_surface
  ON asset_inventory_reservations(surface, status, reserved_at);

CREATE UNIQUE INDEX IF NOT EXISTS idx_asset_inventory_reservations_active_asset
  ON asset_inventory_reservations(asset_id)
  WHERE status IN ('pending', 'committed');

CREATE UNIQUE INDEX IF NOT EXISTS idx_asset_inventory_reservations_idempotency
  ON asset_inventory_reservations(idempotency_key)
  WHERE idempotency_key IS NOT NULL AND idempotency_key != '';

CREATE TABLE IF NOT EXISTS model_account_profiles (
  id TEXT PRIMARY KEY,
  model_id TEXT NOT NULL,
  model_slug TEXT NOT NULL UNIQUE,
  label TEXT NOT NULL,
  allowed_instagram_account_ids_json TEXT NOT NULL DEFAULT '[]',
  allowed_account_group_names_json TEXT NOT NULL DEFAULT '[]',
  allowed_handle_patterns_json TEXT NOT NULL DEFAULT '[]',
  default_smart_link TEXT,
  story_cta_text TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(model_id) REFERENCES models(id) ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS distribution_plans (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  rendered_asset_id TEXT NOT NULL,
  account_id TEXT,
  instagram_account_id TEXT,
  source_family_id TEXT,
  perceptual_fingerprint TEXT,
  perceptual_cluster_id TEXT,
  account_group_id TEXT,
  assignment_eligibility_json TEXT NOT NULL DEFAULT '{}',
  surface TEXT NOT NULL DEFAULT 'regular_reel',
  content_surface TEXT NOT NULL DEFAULT 'reel',
  planned_window_start TEXT,
  planned_window_end TEXT,
  paired_rendered_asset_id TEXT,
  reason_code TEXT,
  smart_link TEXT,
  cta_text TEXT,
  instagram_trial_reels INTEGER NOT NULL DEFAULT 0,
  trial_graduation_strategy TEXT,
  trial_group_id TEXT,
  caption_hash TEXT,
  caption_text TEXT,
  caption_bank TEXT,
  caption_banks_json TEXT NOT NULL DEFAULT '[]',
  creator_mix TEXT,
  creator_model TEXT,
  frame_type TEXT,
  length_class TEXT,
  format_class TEXT,
  caption_fit_version TEXT,
  suitability_decision TEXT,
  suitability_reason TEXT,
  source_clip TEXT,
  caption_outcome_context_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON UPDATE CASCADE,
  FOREIGN KEY(rendered_asset_id) REFERENCES rendered_assets(id) ON UPDATE CASCADE,
  FOREIGN KEY(paired_rendered_asset_id) REFERENCES rendered_assets(id) ON UPDATE CASCADE,
  FOREIGN KEY(account_id) REFERENCES accounts(id) ON UPDATE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_model_account_profiles_model ON model_account_profiles(model_id);
CREATE INDEX IF NOT EXISTS idx_distribution_plans_campaign ON distribution_plans(campaign_id, created_at);
CREATE INDEX IF NOT EXISTS idx_distribution_plans_rendered ON distribution_plans(rendered_asset_id);
CREATE INDEX IF NOT EXISTS idx_distribution_plans_account ON distribution_plans(instagram_account_id);

CREATE TABLE IF NOT EXISTS promotions (
  id TEXT PRIMARY KEY,
  promotion_type TEXT NOT NULL DEFAULT 'reel_ledger',
  campaign_id TEXT NOT NULL,
  rendered_asset_id TEXT NOT NULL,
  account_id TEXT NOT NULL,
  account_group_id TEXT NOT NULL,
  posting_slot_id TEXT NOT NULL,
  content_fingerprint TEXT NOT NULL,
  trial_post_id TEXT,
  source_system TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(content_fingerprint, account_id),
  UNIQUE(account_id, posting_slot_id),
  UNIQUE(trial_post_id),
  FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON UPDATE CASCADE,
  FOREIGN KEY(rendered_asset_id) REFERENCES rendered_assets(id) ON UPDATE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_promotions_cross_account_window
  ON promotions(content_fingerprint, account_id, created_at);

CREATE TABLE IF NOT EXISTS promotion_events (
  id TEXT PRIMARY KEY,
  promotion_id TEXT NOT NULL,
  rendered_asset_id TEXT NOT NULL,
  content_fingerprint TEXT NOT NULL,
  account_id TEXT NOT NULL,
  posting_slot_id TEXT NOT NULL,
  action TEXT NOT NULL CHECK(action IN ('previewed', 'created', 'updated', 'backfilled', 'reconciled', 'rejected')),
  reason TEXT,
  actor TEXT NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  FOREIGN KEY(promotion_id) REFERENCES promotions(id) ON UPDATE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_promotion_events_promotion
  ON promotion_events(promotion_id, created_at);

CREATE TABLE IF NOT EXISTS trial_reel_observations (
  id TEXT PRIMARY KEY,
  trial_post_id TEXT NOT NULL,
  distribution_plan_id TEXT,
  account_id TEXT NOT NULL,
  observed_hours INTEGER NOT NULL CHECK(observed_hours IN (1, 24)),
  views INTEGER NOT NULL DEFAULT 0,
  engagement INTEGER NOT NULL DEFAULT 0,
  metrics_json TEXT NOT NULL DEFAULT '{}',
  observed_at TEXT NOT NULL,
  UNIQUE(trial_post_id, observed_hours),
  FOREIGN KEY(distribution_plan_id) REFERENCES distribution_plans(id) ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS account_content_requirements (
  id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL,
  creator TEXT NOT NULL,
  content_surface TEXT NOT NULL,
  cadence TEXT NOT NULL DEFAULT 'daily',
  max_per_day INTEGER NOT NULL DEFAULT 1,
  min_gap_hours INTEGER NOT NULL DEFAULT 20,
  main_reels_per_day INTEGER NOT NULL DEFAULT 1,
  trial_reels_per_day INTEGER NOT NULL DEFAULT 2,
  allowed_days TEXT NOT NULL DEFAULT '[]',
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(account_id, content_surface),
  FOREIGN KEY(account_id) REFERENCES accounts(id) ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS asset_components (
  id TEXT PRIMARY KEY,
  asset_id TEXT NOT NULL,
  component_index INTEGER NOT NULL,
  media_path TEXT NOT NULL,
  media_hash TEXT,
  media_type TEXT NOT NULL,
  aspect_ratio TEXT,
  alt_text TEXT,
  publishability_state TEXT NOT NULL DEFAULT 'pending',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(asset_id, component_index),
  FOREIGN KEY(asset_id) REFERENCES rendered_assets(id) ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS reference_patterns (
  id TEXT PRIMARY KEY,
  cluster_key TEXT NOT NULL UNIQUE,
  rank INTEGER,
  label TEXT NOT NULL,
  visual_format TEXT,
  hook_type TEXT,
  caption_archetype TEXT,
  reference_ids_json TEXT NOT NULL DEFAULT '[]',
  local_paths_json TEXT NOT NULL DEFAULT '[]',
  public_urls_json TEXT NOT NULL DEFAULT '[]',
  prompt_template_json TEXT NOT NULL DEFAULT '{}',
  higgsfield_json TEXT NOT NULL DEFAULT '{}',
  caption_formulas_json TEXT NOT NULL DEFAULT '[]',
  audio_recommendations_json TEXT NOT NULL DEFAULT '{}',
  raw_json TEXT NOT NULL DEFAULT '{}',
  imported_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reference_knowledge_packs (
  id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  source_fingerprint TEXT NOT NULL UNIQUE,
  generated_at TEXT NOT NULL,
  policy_json TEXT NOT NULL,
  summary_json TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  imported_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audio_catalog (
  id TEXT PRIMARY KEY,
  source_audio_id TEXT,
  title TEXT NOT NULL,
  artist_name TEXT,
  platform TEXT NOT NULL,
  native_audio_id TEXT,
  native_audio_url TEXT,
  mood_tags_json TEXT NOT NULL DEFAULT '[]',
  best_content_types_json TEXT NOT NULL DEFAULT '[]',
  account_fit_json TEXT NOT NULL DEFAULT '[]',
  trend_status TEXT NOT NULL DEFAULT 'unknown',
  usage_count INTEGER,
  bpm REAL,
  energy REAL,
  vocality TEXT,
  confidence REAL,
  safe_usage_notes TEXT,
  trend_score REAL,
  velocity_score REAL,
  fatigue_score REAL,
  account_fit_score REAL,
  creator_fit_score REAL,
  recommendation_confidence TEXT,
  performance_lift REAL,
  source_confidence REAL,
  trend_sources_json TEXT NOT NULL DEFAULT '[]',
  resolved INTEGER NOT NULL DEFAULT 0,
  review_reasons_json TEXT NOT NULL DEFAULT '[]',
  example_reels_json TEXT NOT NULL DEFAULT '[]',
  performance_summary_json TEXT NOT NULL DEFAULT '{}',
  fatigue_json TEXT NOT NULL DEFAULT '{}',
  raw_json TEXT NOT NULL DEFAULT '{}',
  imported_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(platform, source_audio_id),
  UNIQUE(platform, native_audio_id)
);

CREATE TABLE IF NOT EXISTS audio_trend_snapshots (
  id TEXT PRIMARY KEY,
  audio_catalog_id TEXT NOT NULL,
  platform TEXT NOT NULL,
  native_audio_id TEXT,
  observed_at TEXT NOT NULL,
  trend_status TEXT NOT NULL DEFAULT 'unknown',
  usage_count INTEGER,
  saturation_score REAL,
  velocity_score REAL,
  source TEXT,
  notes TEXT,
  raw_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  UNIQUE(audio_catalog_id, observed_at),
  FOREIGN KEY(audio_catalog_id) REFERENCES audio_catalog(id) ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS audio_selections (
  id TEXT PRIMARY KEY,
  recommendation_item_id TEXT,
  campaign_id TEXT,
  rendered_asset_id TEXT,
  post_id TEXT,
  audio_catalog_id TEXT,
  status TEXT NOT NULL DEFAULT 'selected',
  proof_url TEXT,
  proof_note TEXT,
  selected_by TEXT,
  selected_at TEXT,
  verified_at TEXT,
  payload_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(recommendation_item_id, audio_catalog_id),
  FOREIGN KEY(recommendation_item_id) REFERENCES recommendation_items(id) ON UPDATE CASCADE,
  FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON UPDATE CASCADE,
  FOREIGN KEY(rendered_asset_id) REFERENCES rendered_assets(id) ON UPDATE CASCADE,
  FOREIGN KEY(audio_catalog_id) REFERENCES audio_catalog(id) ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS audio_performance_rollups (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  account_id TEXT,
  instagram_account_id TEXT,
  audio_catalog_id TEXT,
  audio_key TEXT NOT NULL,
  post_count INTEGER NOT NULL DEFAULT 0,
  view_count INTEGER NOT NULL DEFAULT 0,
  like_count INTEGER NOT NULL DEFAULT 0,
  save_count INTEGER NOT NULL DEFAULT 0,
  share_count INTEGER NOT NULL DEFAULT 0,
  score REAL,
  last_snapshot_at TEXT,
  stats_json TEXT NOT NULL DEFAULT '{}',
  updated_at TEXT NOT NULL,
  UNIQUE(campaign_id, account_id, instagram_account_id, audio_key),
  FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON UPDATE CASCADE,
  FOREIGN KEY(audio_catalog_id) REFERENCES audio_catalog(id) ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS campaign_reference_plans (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  reference_pattern_id TEXT NOT NULL,
  variant_count INTEGER NOT NULL DEFAULT 5,
  notes TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON UPDATE CASCADE,
  FOREIGN KEY(reference_pattern_id) REFERENCES reference_patterns(id) ON UPDATE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_reference_patterns_rank ON reference_patterns(rank);
CREATE INDEX IF NOT EXISTS idx_audio_catalog_platform ON audio_catalog(platform, trend_status);
CREATE INDEX IF NOT EXISTS idx_audio_trend_snapshots_audio ON audio_trend_snapshots(audio_catalog_id, observed_at);
CREATE INDEX IF NOT EXISTS idx_audio_selections_recommendation ON audio_selections(recommendation_item_id, status);
CREATE INDEX IF NOT EXISTS idx_audio_performance_campaign ON audio_performance_rollups(campaign_id, updated_at);
CREATE INDEX IF NOT EXISTS idx_campaign_reference_plans_campaign ON campaign_reference_plans(campaign_id, created_at);

CREATE TABLE IF NOT EXISTS recommendation_runs (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  scope TEXT NOT NULL DEFAULT 'next_batch',
  scoring_version TEXT NOT NULL,
  input_hash TEXT NOT NULL,
  input_snapshot_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(campaign_id, scope, input_hash),
  FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS recommendation_items (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  rank INTEGER NOT NULL,
  target_account TEXT,
  reference_pattern_id TEXT,
  source_asset_id TEXT,
  rendered_asset_id TEXT,
  recommendation_graph_id TEXT,
  status TEXT NOT NULL DEFAULT 'proposed',
  execution_status TEXT NOT NULL DEFAULT 'not_started',
  score INTEGER NOT NULL,
  confidence TEXT NOT NULL,
  reasons_json TEXT NOT NULL DEFAULT '[]',
  risks_json TEXT NOT NULL DEFAULT '[]',
  evidence_json TEXT NOT NULL DEFAULT '{}',
  data_quality_json TEXT NOT NULL DEFAULT '{}',
  decision_json TEXT NOT NULL DEFAULT '{}',
  outcome_json TEXT NOT NULL DEFAULT '{}',
  baseline_json TEXT NOT NULL DEFAULT '{}',
  measurement_version TEXT,
  output_json TEXT NOT NULL DEFAULT '{}',
  accepted_at TEXT,
  rejected_at TEXT,
  executed_at TEXT,
  posted_at TEXT,
  measured_at TEXT,
  created_at TEXT NOT NULL,
  UNIQUE(run_id, rank),
  FOREIGN KEY(run_id) REFERENCES recommendation_runs(id) ON DELETE CASCADE,
  FOREIGN KEY(reference_pattern_id) REFERENCES reference_patterns(id) ON UPDATE CASCADE,
  FOREIGN KEY(source_asset_id) REFERENCES source_assets(id) ON UPDATE CASCADE,
  FOREIGN KEY(rendered_asset_id) REFERENCES rendered_assets(id) ON UPDATE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_recommendation_runs_campaign ON recommendation_runs(campaign_id, created_at);
CREATE INDEX IF NOT EXISTS idx_recommendation_items_run ON recommendation_items(run_id, rank);
CREATE INDEX IF NOT EXISTS idx_recommendation_items_rendered ON recommendation_items(rendered_asset_id);
CREATE INDEX IF NOT EXISTS idx_recommendation_items_status ON recommendation_items(status, created_at);

CREATE TABLE IF NOT EXISTS trust_settings (
  key TEXT PRIMARY KEY,
  value_json TEXT NOT NULL DEFAULT '{}',
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS account_memory (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  account_id TEXT NOT NULL,
  platform TEXT NOT NULL DEFAULT 'instagram',
  sample_size INTEGER NOT NULL DEFAULT 0,
  confidence TEXT NOT NULL DEFAULT 'low',
  performance_score INTEGER,
  pattern_stats_json TEXT NOT NULL DEFAULT '[]',
  posting_windows_json TEXT NOT NULL DEFAULT '[]',
  fatigue_json TEXT NOT NULL DEFAULT '{}',
  audience_notes_json TEXT NOT NULL DEFAULT '{}',
  recommendation_outcomes_json TEXT NOT NULL DEFAULT '{}',
  updated_at TEXT NOT NULL,
  UNIQUE(campaign_id, account_id),
  FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON UPDATE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_account_memory_campaign
  ON account_memory(campaign_id, account_id);

CREATE TABLE IF NOT EXISTS account_pattern_stats (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  account_id TEXT NOT NULL,
  pattern_key TEXT NOT NULL,
  pattern_type TEXT NOT NULL,
  label TEXT,
  sample_size INTEGER NOT NULL DEFAULT 0,
  performance_score INTEGER,
  fatigue_score INTEGER NOT NULL DEFAULT 0,
  stats_json TEXT NOT NULL DEFAULT '{}',
  updated_at TEXT NOT NULL,
  UNIQUE(campaign_id, account_id, pattern_type, pattern_key),
  FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON UPDATE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_account_pattern_stats_campaign
  ON account_pattern_stats(campaign_id, account_id, pattern_type);

CREATE TABLE IF NOT EXISTS account_posting_windows (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  account_id TEXT NOT NULL,
  weekday INTEGER NOT NULL,
  hour INTEGER NOT NULL,
  sample_size INTEGER NOT NULL DEFAULT 0,
  performance_score INTEGER,
  stats_json TEXT NOT NULL DEFAULT '{}',
  updated_at TEXT NOT NULL,
  UNIQUE(campaign_id, account_id, weekday, hour),
  FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS account_recommendation_outcomes (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  account_id TEXT NOT NULL,
  recommendation_item_id TEXT NOT NULL,
  status TEXT NOT NULL,
  outcome_score INTEGER,
  baseline_score INTEGER,
  lift INTEGER,
  payload_json TEXT NOT NULL DEFAULT '{}',
  updated_at TEXT NOT NULL,
  UNIQUE(campaign_id, account_id, recommendation_item_id),
  FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON UPDATE CASCADE,
  FOREIGN KEY(recommendation_item_id) REFERENCES recommendation_items(id) ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS recommendation_accuracy_observations (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  account_id TEXT,
  recommendation_item_id TEXT NOT NULL,
  recommendation_run_id TEXT NOT NULL,
  reference_pattern_id TEXT,
  selected_audio_key TEXT,
  audio_match_status TEXT NOT NULL DEFAULT 'unknown',
  status TEXT NOT NULL,
  confidence TEXT NOT NULL,
  confidence_bucket TEXT NOT NULL,
  data_quality_level TEXT NOT NULL DEFAULT 'low',
  outcome_score INTEGER,
  baseline_score INTEGER,
  lift INTEGER,
  is_success INTEGER,
  is_inconclusive INTEGER NOT NULL DEFAULT 0,
  measured_at TEXT,
  measurement_version TEXT,
  payload_json TEXT NOT NULL DEFAULT '{}',
  updated_at TEXT NOT NULL,
  UNIQUE(recommendation_item_id),
  FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON UPDATE CASCADE,
  FOREIGN KEY(recommendation_item_id) REFERENCES recommendation_items(id) ON UPDATE CASCADE,
  FOREIGN KEY(recommendation_run_id) REFERENCES recommendation_runs(id) ON UPDATE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_recommendation_accuracy_campaign
  ON recommendation_accuracy_observations(campaign_id, measured_at);

CREATE INDEX IF NOT EXISTS idx_recommendation_accuracy_account
  ON recommendation_accuracy_observations(campaign_id, account_id, measured_at);

CREATE TABLE IF NOT EXISTS recommendation_accuracy_reports (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  account_id TEXT,
  account_key TEXT NOT NULL DEFAULT '',
  window_days INTEGER NOT NULL DEFAULT 30,
  input_hash TEXT NOT NULL,
  report_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(campaign_id, account_key, window_days, input_hash),
  FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON UPDATE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_recommendation_accuracy_reports_campaign
  ON recommendation_accuracy_reports(campaign_id, updated_at);

CREATE TABLE IF NOT EXISTS trust_exceptions (
  id TEXT PRIMARY KEY,
  status TEXT NOT NULL DEFAULT 'open',
  severity TEXT NOT NULL DEFAULT 'medium',
  reason_code TEXT NOT NULL,
  entity_graph_id TEXT,
  recommendation_item_id TEXT,
  campaign_id TEXT,
  account_id TEXT,
  payload_json TEXT NOT NULL DEFAULT '{}',
  resolution_json TEXT NOT NULL DEFAULT '{}',
  snoozed_until TEXT,
  resolved_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(recommendation_item_id) REFERENCES recommendation_items(id) ON UPDATE CASCADE,
  FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON UPDATE CASCADE,
  FOREIGN KEY(entity_graph_id) REFERENCES content_graph_nodes(global_id) ON UPDATE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_trust_exceptions_open_unique
  ON trust_exceptions(
    COALESCE(campaign_id, ''),
    reason_code,
    COALESCE(entity_graph_id, ''),
    COALESCE(recommendation_item_id, ''),
    COALESCE(account_id, '')
  )
  WHERE status IN ('open', 'snoozed');

CREATE INDEX IF NOT EXISTS idx_trust_exceptions_campaign_status
  ON trust_exceptions(campaign_id, status, severity);

CREATE TABLE IF NOT EXISTS content_graph_nodes (
  global_id TEXT PRIMARY KEY,
  entity_type TEXT NOT NULL,
  local_table TEXT,
  local_id TEXT,
  external_system TEXT,
  external_id TEXT,
  payload_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_content_graph_nodes_local
  ON content_graph_nodes(local_table, local_id)
  WHERE local_table IS NOT NULL AND local_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_content_graph_nodes_external
  ON content_graph_nodes(external_system, external_id)
  WHERE external_system IS NOT NULL AND external_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_content_graph_nodes_type
  ON content_graph_nodes(entity_type, updated_at);

CREATE TABLE IF NOT EXISTS content_graph_edges (
  id TEXT PRIMARY KEY,
  from_global_id TEXT NOT NULL,
  to_global_id TEXT NOT NULL,
  relation_type TEXT NOT NULL,
  evidence_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  FOREIGN KEY(from_global_id) REFERENCES content_graph_nodes(global_id) ON UPDATE CASCADE,
  FOREIGN KEY(to_global_id) REFERENCES content_graph_nodes(global_id) ON UPDATE CASCADE,
  UNIQUE(from_global_id, to_global_id, relation_type)
);

CREATE INDEX IF NOT EXISTS idx_content_graph_edges_from
  ON content_graph_edges(from_global_id, relation_type);

CREATE INDEX IF NOT EXISTS idx_content_graph_edges_to
  ON content_graph_edges(to_global_id, relation_type);

CREATE TABLE IF NOT EXISTS content_graph_sync_state (
  system TEXT PRIMARY KEY,
  cursor_json TEXT NOT NULL DEFAULT '{}',
  last_synced_at TEXT NOT NULL
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    # Shared opener applies timeout + busy_timeout (overlapping cron writers
    # wait instead of failing with "database is locked") and WAL (readers
    # proceed during writes). foreign_keys stays campaign-specific.
    conn = connect_sqlite(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    _ensure_columns(conn, "accounts", {"account_group_id": "TEXT"})
    _ensure_columns(
        conn,
        "audit_reports",
        {
            "layers_json": "TEXT NOT NULL DEFAULT '{}'",
            "verdicts_json": "TEXT NOT NULL DEFAULT '{}'",
            "overall_verdict": "TEXT",
            "files_analyzed": "INTEGER NOT NULL DEFAULT 0",
        },
    )
    _ensure_columns(
        conn,
        "rendered_assets",
        {
            "media_type": "TEXT NOT NULL DEFAULT 'video'",
            "content_surface": "TEXT NOT NULL DEFAULT 'reel'",
            "parent_asset_id": "TEXT",
            "concept_id": "TEXT",
            "parent_reel_id": "TEXT",
            "variant_family_id": "TEXT",
            "variant_id": "TEXT",
            "variant_index": "INTEGER",
            "variant_operations_json": "TEXT NOT NULL DEFAULT '[]'",
            "caption_generation_json": "TEXT NOT NULL DEFAULT '{}'",
            "caption_hash": "TEXT",
            "caption_bank": "TEXT",
            "caption_banks_json": "TEXT NOT NULL DEFAULT '[]'",
            "creator_mix": "TEXT",
            "creator_model": "TEXT",
            "frame_type": "TEXT",
            "length_class": "TEXT",
            "format_class": "TEXT",
            "caption_fit_version": "TEXT",
            "suitability_decision": "TEXT",
            "suitability_reason": "TEXT",
            "source_clip": "TEXT",
            "caption_outcome_context_json": "TEXT NOT NULL DEFAULT '{}'",
            "metrics_eligible": "INTEGER NOT NULL DEFAULT 0",
            "story_asset_class": "TEXT",
            "story_cta_type": "TEXT",
            "story_cta_text": "TEXT",
            "story_cta_target_url": "TEXT",
            "story_intent": "TEXT",
            "story_goal": "TEXT",
            "story_style": "TEXT",
            "snapchat_username": "TEXT",
            "snapchat_display_name": "TEXT",
            "snapchat_cta_text": "TEXT",
            "metadata_json": "TEXT NOT NULL DEFAULT '{}'",
            "origin_account_id": "TEXT",
        },
    )
    _ensure_columns(
        conn,
        "performance_snapshots",
        {
            "metrics_eligible": "INTEGER NOT NULL DEFAULT 0",
            "concept_id": "TEXT",
            "parent_reel_id": "TEXT",
            "caption_family_id": "TEXT",
            "caption_version_id": "TEXT",
            "caption_angle": "TEXT",
            "burned_caption_hash": "TEXT",
            "instagram_post_caption_hash": "TEXT",
            "variant_family_id": "TEXT",
            "variant_id": "TEXT",
            "variant_index": "INTEGER",
            "variant_operations_json": "TEXT NOT NULL DEFAULT '[]'",
            "audio_id": "TEXT",
            "content_surface": "TEXT NOT NULL DEFAULT 'reel'",
            "history_source": "TEXT",
            "lineage_v2_valid": "INTEGER NOT NULL DEFAULT 0",
        },
    )
    _ensure_columns(
        conn,
        "proof_runs",
        {
            "current_state": "TEXT NOT NULL DEFAULT 'creative_approved'",
            "blocking_reason": "TEXT",
            "root_cause": "TEXT",
            "metrics_eligible": "INTEGER NOT NULL DEFAULT 0",
            "metadata_json": "TEXT NOT NULL DEFAULT '{}'",
            "completed_at": "TEXT",
        },
    )
    _ensure_columns(
        conn,
        "quarantined_assets",
        {
            "distribution_plan_id": "TEXT",
            "threadsdash_post_id": "TEXT",
            "root_cause": "TEXT",
            "blocking_reason": "TEXT",
            "excluded_from_metrics": "INTEGER NOT NULL DEFAULT 1",
            "metadata_json": "TEXT NOT NULL DEFAULT '{}'",
            "created_by": "TEXT",
        },
    )
    _ensure_columns(
        conn,
        "reference_patterns",
        {
            "audio_recommendations_json": "TEXT NOT NULL DEFAULT '{}'",
        },
    )
    _ensure_columns(
        conn,
        "audio_catalog",
        {
            "confidence": "REAL",
            "safe_usage_notes": "TEXT",
            "trend_score": "REAL",
            "velocity_score": "REAL",
            "fatigue_score": "REAL",
            "account_fit_score": "REAL",
            "creator_fit_score": "REAL",
            "recommendation_confidence": "TEXT",
            "performance_lift": "REAL",
            "source_confidence": "REAL",
            "trend_sources_json": "TEXT NOT NULL DEFAULT '[]'",
            "resolved": "INTEGER NOT NULL DEFAULT 0",
            "review_reasons_json": "TEXT NOT NULL DEFAULT '[]'",
            "example_reels_json": "TEXT NOT NULL DEFAULT '[]'",
            "performance_summary_json": "TEXT NOT NULL DEFAULT '{}'",
            "fatigue_json": "TEXT NOT NULL DEFAULT '{}'",
        },
    )
    _ensure_columns(
        conn,
        "source_assets",
        {
            "media_type": "TEXT NOT NULL DEFAULT 'video'",
            "content_surface": "TEXT NOT NULL DEFAULT 'reel'",
        },
    )
    _ensure_columns(
        conn,
        "performance_snapshots",
        {
            "impressions": "INTEGER",
            "caption_text": "TEXT",
            "caption_family_id": "TEXT",
            "caption_version_id": "TEXT",
            "caption_angle": "TEXT",
            "burned_caption_hash": "TEXT",
            "instagram_post_caption_hash": "TEXT",
            "caption_bank": "TEXT",
            "caption_banks_json": "TEXT NOT NULL DEFAULT '[]'",
            "creator_mix": "TEXT",
            "creator_model": "TEXT",
            "frame_type": "TEXT",
            "length_class": "TEXT",
            "format_class": "TEXT",
            "caption_fit_version": "TEXT",
            "suitability_decision": "TEXT",
            "suitability_reason": "TEXT",
            "source_clip": "TEXT",
            "caption_outcome_context_json": "TEXT NOT NULL DEFAULT '{}'",
            "concept_id": "TEXT",
            "parent_reel_id": "TEXT",
            "variant_family_id": "TEXT",
            "variant_id": "TEXT",
            "variant_index": "INTEGER",
            "variant_operations_json": "TEXT NOT NULL DEFAULT '[]'",
            "audio_id": "TEXT",
            "content_surface": "TEXT NOT NULL DEFAULT 'reel'",
            "history_source": "TEXT",
            "lineage_v2_valid": "INTEGER NOT NULL DEFAULT 0",
        },
    )
    _ensure_columns(
        conn,
        "asset_account_assignments",
        {
            "caption_hash": "TEXT",
            "caption_text": "TEXT",
            "caption_bank": "TEXT",
            "caption_banks_json": "TEXT NOT NULL DEFAULT '[]'",
            "creator_mix": "TEXT",
            "creator_model": "TEXT",
            "frame_type": "TEXT",
            "length_class": "TEXT",
            "format_class": "TEXT",
            "caption_fit_version": "TEXT",
            "suitability_decision": "TEXT",
            "suitability_reason": "TEXT",
            "source_clip": "TEXT",
            "caption_outcome_context_json": "TEXT NOT NULL DEFAULT '{}'",
            "instagram_trial_reels": "INTEGER NOT NULL DEFAULT 0",
            "trial_graduation_strategy": "TEXT",
            "source_family_id": "TEXT",
            "perceptual_fingerprint": "TEXT",
            "perceptual_cluster_id": "TEXT",
            "account_group_id": "TEXT",
            "assignment_eligibility_json": "TEXT NOT NULL DEFAULT '{}'",
        },
    )
    _ensure_columns(
        conn,
        "distribution_plans",
        {
            "concept_id": "TEXT",
            "parent_reel_id": "TEXT",
            "caption_family_id": "TEXT",
            "caption_version_id": "TEXT",
            "caption_angle": "TEXT",
            "burned_caption_hash": "TEXT",
            "instagram_post_caption_hash": "TEXT",
            "variant_family_id": "TEXT",
            "variant_id": "TEXT",
            "variant_index": "INTEGER",
            "variant_operations_json": "TEXT NOT NULL DEFAULT '[]'",
            "content_surface": "TEXT NOT NULL DEFAULT 'reel'",
            "caption_hash": "TEXT",
            "caption_text": "TEXT",
            "caption_bank": "TEXT",
            "caption_banks_json": "TEXT NOT NULL DEFAULT '[]'",
            "creator_mix": "TEXT",
            "creator_model": "TEXT",
            "frame_type": "TEXT",
            "length_class": "TEXT",
            "format_class": "TEXT",
            "caption_fit_version": "TEXT",
            "suitability_decision": "TEXT",
            "suitability_reason": "TEXT",
            "source_clip": "TEXT",
            "caption_outcome_context_json": "TEXT NOT NULL DEFAULT '{}'",
            "story_asset_class": "TEXT",
            "story_cta_type": "TEXT",
            "story_cta_text": "TEXT",
            "story_cta_target_url": "TEXT",
            "story_intent": "TEXT",
            "story_goal": "TEXT",
            "story_style": "TEXT",
            "snapchat_username": "TEXT",
            "snapchat_display_name": "TEXT",
            "snapchat_cta_text": "TEXT",
            "instagram_trial_reels": "INTEGER NOT NULL DEFAULT 0",
            "trial_graduation_strategy": "TEXT",
            "trial_group_id": "TEXT",
            "source_family_id": "TEXT",
            "perceptual_fingerprint": "TEXT",
            "perceptual_cluster_id": "TEXT",
            "account_group_id": "TEXT",
            "assignment_eligibility_json": "TEXT NOT NULL DEFAULT '{}'",
        },
    )
    _ensure_columns(
        conn,
        "asset_inventory_reservations",
        {"assignment_eligibility_json": "TEXT NOT NULL DEFAULT '{}'"},
    )
    _ensure_columns(conn, "promotions", {"account_group_id": "TEXT"})
    _ensure_columns(
        conn,
        "promotion_events",
        {
            "rendered_asset_id": "TEXT",
            "content_fingerprint": "TEXT",
            "account_id": "TEXT",
            "posting_slot_id": "TEXT",
            "reason": "TEXT",
        },
    )
    conn.execute(
        """
        UPDATE promotions
        SET account_group_id = COALESCE(
            NULLIF(account_group_id, ''),
            (
                SELECT COALESCE(NULLIF(a.account_group_id, ''), NULLIF(a.model_id, ''))
                FROM accounts a
                WHERE a.id = promotions.account_id
            ),
            campaign_id
        )
        WHERE account_group_id IS NULL OR account_group_id = ''
        """
    )
    conn.execute(
        """
        UPDATE promotion_events
        SET rendered_asset_id = COALESCE(
                NULLIF(rendered_asset_id, ''),
                (SELECT p.rendered_asset_id FROM promotions p WHERE p.id = promotion_events.promotion_id)
            ),
            content_fingerprint = COALESCE(
                NULLIF(content_fingerprint, ''),
                (SELECT p.content_fingerprint FROM promotions p WHERE p.id = promotion_events.promotion_id)
            ),
            account_id = COALESCE(
                NULLIF(account_id, ''),
                (SELECT p.account_id FROM promotions p WHERE p.id = promotion_events.promotion_id)
            ),
            posting_slot_id = COALESCE(
                NULLIF(posting_slot_id, ''),
                (SELECT p.posting_slot_id FROM promotions p WHERE p.id = promotion_events.promotion_id)
            )
        WHERE rendered_asset_id IS NULL OR rendered_asset_id = ''
           OR content_fingerprint IS NULL OR content_fingerprint = ''
           OR account_id IS NULL OR account_id = ''
           OR posting_slot_id IS NULL OR posting_slot_id = ''
        """
    )
    _ensure_columns(
        conn,
        "account_content_requirements",
        {
            "main_reels_per_day": "INTEGER NOT NULL DEFAULT 1",
            "trial_reels_per_day": "INTEGER NOT NULL DEFAULT 2",
        },
    )
    _ensure_columns(
        conn,
        "variant_families",
        {
            "caption_family_id": "TEXT",
            "caption_version_id": "TEXT",
            "content_surface": "TEXT NOT NULL DEFAULT 'reel'",
        },
    )
    _ensure_columns(
        conn,
        "variant_assets",
        {
            "caption_family_id": "TEXT",
            "caption_version_id": "TEXT",
            "content_surface": "TEXT NOT NULL DEFAULT 'reel'",
        },
    )
    _ensure_columns(
        conn,
        "recommendation_items",
        {
            "status": "TEXT NOT NULL DEFAULT 'proposed'",
            "execution_status": "TEXT NOT NULL DEFAULT 'not_started'",
            "evidence_json": "TEXT NOT NULL DEFAULT '{}'",
            "data_quality_json": "TEXT NOT NULL DEFAULT '{}'",
            "decision_json": "TEXT NOT NULL DEFAULT '{}'",
            "outcome_json": "TEXT NOT NULL DEFAULT '{}'",
            "baseline_json": "TEXT NOT NULL DEFAULT '{}'",
            "measurement_version": "TEXT",
            "accepted_at": "TEXT",
            "rejected_at": "TEXT",
            "executed_at": "TEXT",
            "posted_at": "TEXT",
            "measured_at": "TEXT",
        },
    )
    _ensure_columns(
        conn,
        "trust_exceptions",
        {
            "snoozed_until": "TEXT",
        },
    )
    _ensure_columns(
        conn,
        "recommendation_accuracy_reports",
        {
            "account_key": "TEXT NOT NULL DEFAULT ''",
        },
    )
    _migrate_source_assets_hash_scope(conn)
    _migrate_rendered_assets_hash_scope(conn)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_performance_caption_bank ON performance_snapshots(caption_bank)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_caption_versions_parent ON caption_versions(parent_asset_id, caption_family_index)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_caption_versions_angle ON caption_versions(caption_angle)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_performance_caption_version ON performance_snapshots(caption_family_id, caption_version_id, caption_angle)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_source_assets_surface ON source_assets(content_surface)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_rendered_assets_surface ON rendered_assets(content_surface)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_distribution_plans_surface ON distribution_plans(content_surface, surface)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_performance_surface ON performance_snapshots(content_surface, snapshot_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_account_requirements_creator_surface ON account_content_requirements(creator, content_surface, active)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_asset_components_asset_order ON asset_components(asset_id, component_index)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_performance_creator_mix ON performance_snapshots(creator_mix)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_performance_caption_fit ON performance_snapshots(frame_type, length_class, format_class, caption_fit_version)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_performance_learning_eligible "
        "ON performance_snapshots(campaign_id, metrics_eligible, history_source, lineage_v2_valid, published_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_distribution_plans_caption_hash ON distribution_plans(caption_hash)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_promotions_identity_window_v2 "
        "ON promotions(content_fingerprint, account_group_id, created_at, account_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_promotion_events_identity "
        "ON promotion_events(content_fingerprint, account_id, posting_slot_id, created_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_assignment_identity_window "
        "ON asset_account_assignments(account_group_id, source_family_id, perceptual_cluster_id, created_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_distribution_identity_window "
        "ON distribution_plans(account_group_id, source_family_id, perceptual_cluster_id, planned_window_start)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_proof_runs_campaign_asset ON proof_runs(campaign_id, rendered_asset_id, started_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_proof_runs_distribution_plan ON proof_runs(distribution_plan_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_quarantined_assets_campaign ON quarantined_assets(campaign_id, created_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_asset_rejection_evidence_asset ON asset_rejection_evidence(rendered_asset_id, failed_stage, created_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_asset_rejection_evidence_category ON asset_rejection_evidence(failed_stage, failure_category, created_at)"
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_asset_inventory_reservations_active_asset
        ON asset_inventory_reservations(asset_id)
        WHERE status IN ('pending', 'committed')
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_asset_inventory_reservations_idempotency
        ON asset_inventory_reservations(idempotency_key)
        WHERE idempotency_key IS NOT NULL AND idempotency_key != ''
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_asset_inventory_reservations_uniqueness
        ON asset_inventory_reservations(campaign_id, surface, source_family_id, perceptual_cluster_id, status, reserved_at)
        """
    )
    # Dedupe legacy rows before enforcing uniqueness (keep earliest insert).
    conn.execute(
        """
        DELETE FROM asset_account_assignments WHERE rowid NOT IN (
          SELECT MIN(rowid) FROM asset_account_assignments
          GROUP BY rendered_asset_id, COALESCE(account_id, ''),
                   COALESCE(instagram_account_id, ''), COALESCE(planned_window_start, '')
        )
        """
    )
    conn.execute(
        """
        DELETE FROM distribution_plans WHERE rowid NOT IN (
          SELECT MIN(rowid) FROM distribution_plans
          GROUP BY rendered_asset_id, surface, COALESCE(account_id, ''),
                   COALESCE(instagram_account_id, ''), COALESCE(planned_window_start, '')
        )
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_asset_account_assignments_uniqueness
        ON asset_account_assignments(
          rendered_asset_id, COALESCE(account_id, ''),
          COALESCE(instagram_account_id, ''), COALESCE(planned_window_start, '')
        )
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_distribution_plans_uniqueness
        ON distribution_plans(
          rendered_asset_id, surface, COALESCE(account_id, ''),
          COALESCE(instagram_account_id, ''), COALESCE(planned_window_start, '')
        )
        """
    )
    _repair_source_asset_fk_references(conn)
    _repair_fk_references(conn, "rendered_assets_old_global_hash", "rendered_assets")
    conn.commit()


def _migrate_source_assets_hash_scope(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'source_assets'"
    ).fetchone()
    sql = (row["sql"] if row else "") or ""
    if "content_hash TEXT NOT NULL UNIQUE" not in sql:
        indexes = {
            idx["name"]
            for idx in conn.execute("PRAGMA index_list(source_assets)").fetchall()
        }
        if "idx_source_assets_campaign_hash" not in indexes:
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_source_assets_campaign_hash "
                "ON source_assets(campaign_id, content_hash)"
            )
        return

    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("PRAGMA legacy_alter_table = ON")
    conn.execute("ALTER TABLE source_assets RENAME TO source_assets_old_global_hash")
    conn.execute("PRAGMA legacy_alter_table = OFF")
    conn.execute(
        """
        CREATE TABLE source_assets (
          id TEXT PRIMARY KEY,
          campaign_id TEXT NOT NULL,
          model_id TEXT NOT NULL,
          content_hash TEXT NOT NULL,
          original_path TEXT NOT NULL,
          stored_path TEXT NOT NULL,
          filename TEXT NOT NULL,
          media_type TEXT NOT NULL DEFAULT 'video',
          platform TEXT NOT NULL DEFAULT 'instagram',
          source_prompt TEXT,
          higgsfield_job_id TEXT,
          higgsfield_model TEXT,
          notes TEXT,
          account_ids_json TEXT NOT NULL DEFAULT '[]',
          status TEXT NOT NULL DEFAULT 'imported',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE(campaign_id, content_hash),
          FOREIGN KEY(campaign_id) REFERENCES campaigns(id),
          FOREIGN KEY(model_id) REFERENCES models(id)
        )
        """
    )
    columns = [
        "id",
        "campaign_id",
        "model_id",
        "content_hash",
        "original_path",
        "stored_path",
        "filename",
        "media_type",
        "platform",
        "source_prompt",
        "higgsfield_job_id",
        "higgsfield_model",
        "notes",
        "account_ids_json",
        "status",
        "created_at",
        "updated_at",
    ]
    joined = ", ".join(columns)
    conn.execute(
        f"INSERT INTO source_assets ({joined}) SELECT {joined} FROM source_assets_old_global_hash"
    )
    conn.execute("DROP TABLE source_assets_old_global_hash")
    conn.execute("PRAGMA foreign_keys = ON")


def _migrate_rendered_assets_hash_scope(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'rendered_assets'"
    ).fetchone()
    sql = (row["sql"] if row else "") or ""
    if "content_hash TEXT NOT NULL UNIQUE" not in sql:
        indexes = {
            idx["name"]
            for idx in conn.execute("PRAGMA index_list(rendered_assets)").fetchall()
        }
        if "idx_rendered_assets_campaign_hash" not in indexes:
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_rendered_assets_campaign_hash "
                "ON rendered_assets(campaign_id, content_hash)"
            )
        return

    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("PRAGMA legacy_alter_table = ON")
    conn.execute(
        "ALTER TABLE rendered_assets RENAME TO rendered_assets_old_global_hash"
    )
    conn.execute("PRAGMA legacy_alter_table = OFF")
    conn.execute(
        """
        CREATE TABLE rendered_assets (
          id TEXT PRIMARY KEY,
          campaign_id TEXT NOT NULL,
          source_asset_id TEXT NOT NULL,
          render_job_id TEXT,
          content_hash TEXT NOT NULL,
          output_path TEXT NOT NULL,
          campaign_path TEXT NOT NULL,
          filename TEXT NOT NULL,
          caption TEXT,
          caption_hash TEXT,
          caption_bank TEXT,
          caption_banks_json TEXT NOT NULL DEFAULT '[]',
          creator_mix TEXT,
          creator_model TEXT,
          frame_type TEXT,
          length_class TEXT,
          format_class TEXT,
          caption_fit_version TEXT,
          suitability_decision TEXT,
          suitability_reason TEXT,
          source_clip TEXT,
          caption_outcome_context_json TEXT NOT NULL DEFAULT '{}',
          caption_generation_json TEXT NOT NULL DEFAULT '{}',
          recipe TEXT,
          target_ratio TEXT,
          audit_status TEXT NOT NULL DEFAULT 'pending',
          review_state TEXT NOT NULL DEFAULT 'draft',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE(campaign_id, content_hash),
          FOREIGN KEY(campaign_id) REFERENCES campaigns(id),
          FOREIGN KEY(source_asset_id) REFERENCES source_assets(id),
          FOREIGN KEY(render_job_id) REFERENCES render_jobs(id)
        )
        """
    )
    columns = [
        "id",
        "campaign_id",
        "source_asset_id",
        "render_job_id",
        "content_hash",
        "output_path",
        "campaign_path",
        "filename",
        "caption",
        "caption_hash",
        "caption_bank",
        "caption_banks_json",
        "creator_mix",
        "creator_model",
        "frame_type",
        "length_class",
        "format_class",
        "caption_fit_version",
        "suitability_decision",
        "suitability_reason",
        "source_clip",
        "caption_outcome_context_json",
        "caption_generation_json",
        "recipe",
        "target_ratio",
        "audit_status",
        "review_state",
        "created_at",
        "updated_at",
    ]
    joined = ", ".join(columns)
    conn.execute(
        f"INSERT INTO rendered_assets ({joined}) SELECT {joined} FROM rendered_assets_old_global_hash"
    )
    conn.execute("DROP TABLE rendered_assets_old_global_hash")
    conn.execute("PRAGMA foreign_keys = ON")


def _repair_source_asset_fk_references(conn: sqlite3.Connection) -> None:
    _repair_fk_references(conn, "source_assets_old_global_hash", "source_assets")


def _repair_fk_references(
    conn: sqlite3.Connection, broken_name: str, replacement_name: str
) -> None:
    rows = conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type = 'table' AND sql LIKE ?",
        (f"%{broken_name}%",),
    ).fetchall()
    if not rows:
        return

    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    for row in rows:
        table = row["name"]
        if table == broken_name:
            continue
        old_sql = row["sql"]
        new_sql = old_sql.replace(f'"{broken_name}"', replacement_name).replace(
            broken_name, replacement_name
        )
        temp_table = f"{table}_fk_repair"
        temp_sql = re.sub(
            rf"^CREATE TABLE\s+\"?{re.escape(table)}\"?",
            f"CREATE TABLE {temp_table}",
            new_sql,
            count=1,
            flags=re.I,
        )
        columns = [
            col["name"]
            for col in conn.execute(f"PRAGMA table_info({table})").fetchall()
        ]
        joined = ", ".join(columns)
        conn.execute(f"DROP TABLE IF EXISTS {temp_table}")
        conn.execute(temp_sql)
        conn.execute(
            f"INSERT INTO {temp_table} ({joined}) SELECT {joined} FROM {table}"
        )
        conn.execute(f"DROP TABLE {table}")
        conn.execute("PRAGMA legacy_alter_table = ON")
        conn.execute(f"ALTER TABLE {temp_table} RENAME TO {table}")
        conn.execute("PRAGMA legacy_alter_table = OFF")
    conn.execute("PRAGMA foreign_keys = ON")

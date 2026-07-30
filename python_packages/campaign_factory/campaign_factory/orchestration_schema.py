DAILY_ORCHESTRATION_SCHEMA = """
ALTER TABLE campaign_governance ADD COLUMN production_priority INTEGER NOT NULL DEFAULT 0;

CREATE TABLE daily_orchestrator_runs (
  id TEXT PRIMARY KEY,
  run_key TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL CHECK(status IN ('planned', 'running', 'completed', 'blocked')),
  algorithm_version TEXT NOT NULL,
  policy_fingerprint TEXT NOT NULL,
  requested_items INTEGER NOT NULL CHECK(requested_items > 0),
  selected_items INTEGER NOT NULL CHECK(selected_items >= 0),
  limits_json TEXT NOT NULL,
  stop_reason TEXT NOT NULL,
  next_run_reason TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE daily_orchestrator_items (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
  creator_id TEXT NOT NULL,
  campaign_id TEXT NOT NULL,
  source_asset_id TEXT,
  mode TEXT NOT NULL CHECK(mode IN ('static_reel', 'calm_animation', 'recreate_reel')),
  intent TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN (
    'selected', 'running', 'completed', 'blocked', 'exhausted'
  )),
  attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
  max_attempts INTEGER NOT NULL CHECK(max_attempts > 0),
  next_attempt_at TEXT,
  selection_reason_json TEXT NOT NULL,
  decision_fingerprint TEXT NOT NULL,
  result_json TEXT,
  error_code TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(run_id) REFERENCES daily_orchestrator_runs(id),
  FOREIGN KEY(creator_id) REFERENCES models(id),
  FOREIGN KEY(campaign_id) REFERENCES campaigns(id),
  FOREIGN KEY(source_asset_id) REFERENCES source_assets(id),
  UNIQUE(run_id, ordinal),
  UNIQUE(run_id, campaign_id, source_asset_id)
);

CREATE INDEX idx_daily_orchestrator_items_creator
  ON daily_orchestrator_items(creator_id, created_at);
CREATE INDEX idx_daily_orchestrator_items_campaign
  ON daily_orchestrator_items(campaign_id, created_at);

CREATE TABLE operator_authority_events (
  id TEXT PRIMARY KEY,
  operation_id TEXT NOT NULL,
  effect_class TEXT NOT NULL,
  decision TEXT NOT NULL CHECK(decision IN ('allowed', 'denied')),
  actor_fingerprint TEXT NOT NULL,
  role TEXT NOT NULL,
  request_fingerprint TEXT NOT NULL,
  reason TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TRIGGER daily_orchestrator_runs_no_delete
BEFORE DELETE ON daily_orchestrator_runs
BEGIN
  SELECT RAISE(ABORT, 'daily orchestrator runs are retained evidence');
END;

CREATE TRIGGER daily_orchestrator_items_no_delete
BEFORE DELETE ON daily_orchestrator_items
BEGIN
  SELECT RAISE(ABORT, 'daily orchestrator items are retained evidence');
END;

CREATE TRIGGER operator_authority_events_immutable_update
BEFORE UPDATE ON operator_authority_events
BEGIN
  SELECT RAISE(ABORT, 'operator authority events are append-only');
END;

CREATE TRIGGER operator_authority_events_immutable_delete
BEFORE DELETE ON operator_authority_events
BEGIN
  SELECT RAISE(ABORT, 'operator authority events are append-only');
END;
"""


DAILY_ORCHESTRATION_GUARDS_V2 = """
DROP TRIGGER IF EXISTS operator_authority_events_immutable_update;

CREATE TRIGGER operator_authority_events_immutable_update
BEFORE UPDATE ON operator_authority_events
WHEN NEW.id != OLD.id
  OR NEW.operation_id != OLD.operation_id
  OR NEW.effect_class != OLD.effect_class
  OR NEW.decision != OLD.decision
  OR NEW.actor_fingerprint != OLD.actor_fingerprint
  OR NEW.role != OLD.role
  OR NEW.request_fingerprint != OLD.request_fingerprint
  OR NEW.reason != OLD.reason
  OR NEW.created_at != OLD.created_at
  OR NEW.idempotency_key IS NOT OLD.idempotency_key
  OR NEW.preview != OLD.preview
  OR NEW.apply_requested != OLD.apply_requested
  OR NEW.rollback_owner IS NOT OLD.rollback_owner
  OR NEW.reconciliation_owner IS NOT OLD.reconciliation_owner
  OR NEW.attempt_count < OLD.attempt_count
  OR NEW.attempt_count > OLD.attempt_count + 1
  OR (
    NEW.attempt_count = OLD.attempt_count + 1
    AND NEW.execution_state != 'claimed'
  )
  OR (
    NEW.execution_state = OLD.execution_state
    AND (
      NEW.attempt_count != OLD.attempt_count
      OR NEW.claim_updated_at IS NOT OLD.claim_updated_at
      OR NEW.completed_at IS NOT OLD.completed_at
      OR NEW.outcome_json IS NOT OLD.outcome_json
      OR NEW.error_json IS NOT OLD.error_json
      OR NEW.retryable != OLD.retryable
    )
  )
  OR NOT (
    NEW.execution_state = OLD.execution_state
    OR (OLD.execution_state = 'claimed'
        AND NEW.execution_state IN ('succeeded', 'failed'))
    OR (OLD.execution_state = 'failed'
        AND OLD.retryable = 1
        AND NEW.execution_state = 'claimed')
  )
  OR (
    NEW.execution_state = 'claimed'
    AND (
      NEW.completed_at IS NOT NULL
      OR NEW.outcome_json IS NOT NULL
      OR NEW.error_json IS NOT NULL
      OR NEW.retryable != 0
    )
  )
  OR (
    NEW.execution_state IN ('succeeded', 'failed')
    AND NEW.completed_at IS NULL
  )
  OR (NEW.execution_state = 'succeeded' AND NEW.outcome_json IS NULL)
  OR (NEW.execution_state = 'succeeded' AND NEW.retryable != 0)
  OR (
    OLD.execution_state = 'claimed'
    AND NEW.execution_state IN ('succeeded', 'failed')
    AND (
      NEW.attempt_count != OLD.attempt_count
      OR NEW.claim_updated_at IS NOT OLD.claim_updated_at
    )
  )
BEGIN
  SELECT RAISE(ABORT, 'operator authority event transition is invalid');
END;

CREATE TRIGGER daily_orchestrator_runs_update_guard
BEFORE UPDATE ON daily_orchestrator_runs
WHEN NEW.run_key != OLD.run_key
  OR NEW.algorithm_version != OLD.algorithm_version
  OR NEW.policy_fingerprint != OLD.policy_fingerprint
  OR NEW.requested_items != OLD.requested_items
  OR NEW.selected_items != OLD.selected_items
  OR NEW.limits_json != OLD.limits_json
  OR NEW.stop_reason != OLD.stop_reason
  OR NEW.next_run_reason != OLD.next_run_reason
  OR NEW.created_at != OLD.created_at
  OR (
    OLD.status = 'completed'
    AND NEW.status = 'completed'
    AND NEW.updated_at != OLD.updated_at
  )
  OR NOT (
    NEW.status = OLD.status
    OR (OLD.status = 'planned' AND NEW.status IN ('running', 'completed', 'blocked'))
    OR (OLD.status = 'running' AND NEW.status IN ('completed', 'blocked'))
    OR (OLD.status = 'blocked' AND NEW.status IN ('running', 'completed'))
  )
BEGIN
  SELECT RAISE(ABORT, 'daily orchestrator run evidence is immutable');
END;

CREATE TRIGGER daily_orchestrator_items_update_guard
BEFORE UPDATE ON daily_orchestrator_items
WHEN NEW.run_id != OLD.run_id
  OR NEW.ordinal != OLD.ordinal
  OR NEW.creator_id != OLD.creator_id
  OR NEW.campaign_id != OLD.campaign_id
  OR NEW.source_asset_id IS NOT OLD.source_asset_id
  OR NEW.mode != OLD.mode
  OR NEW.intent != OLD.intent
  OR NEW.max_attempts != OLD.max_attempts
  OR NEW.selection_reason_json != OLD.selection_reason_json
  OR NEW.decision_fingerprint != OLD.decision_fingerprint
  OR NEW.created_at != OLD.created_at
  OR NEW.attempt_count < OLD.attempt_count
  OR NEW.attempt_count > OLD.attempt_count + 1
  OR (NEW.attempt_count = OLD.attempt_count + 1 AND NEW.state != 'running')
  OR NOT (
    NEW.state = OLD.state
    OR (OLD.state = 'selected' AND NEW.state = 'running')
    OR (OLD.state = 'selected' AND NEW.state = 'exhausted')
    OR (OLD.state = 'running' AND NEW.state IN ('completed', 'blocked', 'exhausted'))
    OR (OLD.state = 'blocked' AND NEW.state IN ('running', 'exhausted'))
  )
  OR (NEW.state = 'completed' AND NEW.result_json IS NULL)
  OR (NEW.state != 'completed' AND NEW.result_json IS NOT NULL)
  OR (
    OLD.state = 'completed'
    AND NEW.state = 'completed'
    AND (
      NEW.attempt_count != OLD.attempt_count
      OR NEW.next_attempt_at IS NOT OLD.next_attempt_at
      OR NEW.result_json IS NOT OLD.result_json
      OR NEW.error_code IS NOT OLD.error_code
      OR NEW.updated_at != OLD.updated_at
    )
  )
BEGIN
  SELECT RAISE(ABORT, 'daily orchestrator item evidence is immutable');
END;
"""

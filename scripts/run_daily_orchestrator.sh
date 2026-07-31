#!/bin/bash
set -euo pipefail

ROOT="${CREATOR_OS_RUNTIME_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
MODE="${CREATOR_OS_DAILY_ORCHESTRATOR_MODE:-preview}"
RUN_KEY="${CREATOR_OS_DAILY_ORCHESTRATOR_RUN_KEY:-$(date -u +%F)}"
MAX_ITEMS="${CREATOR_OS_DAILY_ORCHESTRATOR_MAX_ITEMS:-3}"
PER_CREATOR="${CREATOR_OS_DAILY_ORCHESTRATOR_PER_CREATOR:-1}"
PER_CAMPAIGN="${CREATOR_OS_DAILY_ORCHESTRATOR_PER_CAMPAIGN:-1}"
PROVIDER_CAP="${CREATOR_OS_DAILY_ORCHESTRATOR_PROVIDER_CAP:-0}"

args=(
  orchestrate-daily
  --run-key "$RUN_KEY"
  --max-items "$MAX_ITEMS"
  --per-creator-cap "$PER_CREATOR"
  --per-campaign-cap "$PER_CAMPAIGN"
  --provider-cap "$PROVIDER_CAP"
)

case "$MODE" in
  preview) ;;
  plan) args+=(--apply) ;;
  execute) args+=(--apply --execute) ;;
  *)
    echo "CREATOR_OS_DAILY_ORCHESTRATOR_MODE must be preview, plan, or execute" >&2
    exit 64
    ;;
esac

exec "$ROOT/scripts/run_campaign_factory.sh" "${args[@]}"

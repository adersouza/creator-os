#!/bin/bash
# Load the fail-closed provider-credit policy before any Campaign Factory run.
set -euo pipefail

ROOT="${CREATOR_OS_RUNTIME_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
ENV_FILE="${CREATOR_OS_GENERATION_ENV:-$HOME/.creator-os/generation.env}"

if [ ! -f "$ENV_FILE" ]; then
  echo "Creator OS generation policy is missing: $ENV_FILE" >&2
  exit 78
fi

# shellcheck disable=SC1090
source "$ENV_FILE"

: "${HIGGSFIELD_DAILY_BUDGET_CREDITS:?required}"
: "${HIGGSFIELD_MONTHLY_BUDGET_CREDITS:?required}"
: "${HIGGSFIELD_RUN_MAX_ASSETS:?required}"
: "${HIGGSFIELD_RUN_MAX_CREDITS:?required}"
: "${HIGGSFIELD_COHORT_MAX_CREDITS:?required}"
: "${HIGGSFIELD_MIN_BALANCE_CREDITS:?required}"
: "${HIGGSFIELD_KLING_DAILY_MAX_GENERATIONS:?required}"

cd "$ROOT"
exec uv run campaign-factory "$@"

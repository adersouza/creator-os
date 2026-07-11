#!/bin/bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${CREATOR_OS_PERFORMANCE_SYNC_ENV:-$HOME/.creator-os/performance-sync.env}"

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
unset VIRTUAL_ENV PYTHONHOME PYTHONPATH

cd "$REPO_ROOT"
# shellcheck disable=SC1090
source "$ENV_FILE"

: "${CAMPAIGN_FACTORY_DB:?CAMPAIGN_FACTORY_DB is required}"
: "${CAMPAIGN_FACTORY_SYNC_CAMPAIGNS:?CAMPAIGN_FACTORY_SYNC_CAMPAIGNS is required}"

exec uv run python scripts/run_learning_cohort_daily.py --apply

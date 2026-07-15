#!/bin/bash
set -euo pipefail

if [ "$#" -gt 1 ] || { [ "$#" -eq 1 ] && [ "$1" != "--dry-run" ]; }; then
  echo "usage: $0 [--dry-run]" >&2
  exit 2
fi

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${CREATOR_OS_PERFORMANCE_SYNC_ENV:-$HOME/.creator-os/performance-sync.env}"

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
unset VIRTUAL_ENV PYTHONHOME PYTHONPATH

cd "$REPO_ROOT"
# shellcheck disable=SC1090
source "$ENV_FILE"

: "${CAMPAIGN_FACTORY_DB:?CAMPAIGN_FACTORY_DB is required}"
: "${REFERENCE_FACTORY_DB:?REFERENCE_FACTORY_DB is required}"
: "${REEL_FACTORY_MANIFEST_DB:?REEL_FACTORY_MANIFEST_DB is required}"
: "${CAMPAIGN_FACTORY_SYNC_CAMPAIGNS:?CAMPAIGN_FACTORY_SYNC_CAMPAIGNS is required}"

campaign="$(python3 - <<'PY'
import json
import os

campaigns = json.loads(os.environ["CAMPAIGN_FACTORY_SYNC_CAMPAIGNS"])
if campaigns != ["stacey_learning_cohort_v1"]:
    raise SystemExit(
        "performance-sync campaign scope must be exactly stacey_learning_cohort_v1"
    )
print(campaigns[0])
PY
)"

if [ ! -f "$CAMPAIGN_FACTORY_DB" ]; then
  echo "performance-sync database missing: $CAMPAIGN_FACTORY_DB" >&2
  exit 2
fi
if [ ! -f "$REFERENCE_FACTORY_DB" ]; then
  echo "performance-sync reference database missing: $REFERENCE_FACTORY_DB" >&2
  exit 2
fi
if [ ! -f "$REEL_FACTORY_MANIFEST_DB" ]; then
  echo "performance-sync reel manifest missing: $REEL_FACTORY_MANIFEST_DB" >&2
  exit 2
fi
if ! sqlite3 "$CAMPAIGN_FACTORY_DB" \
  "SELECT 1 FROM campaigns WHERE slug = '$campaign' LIMIT 1;" | grep -qx 1; then
  echo "performance-sync campaign missing from configured database: $campaign ($CAMPAIGN_FACTORY_DB)" >&2
  exit 2
fi

exec python3 scripts/sync_threadsdash_performance.py "$@"

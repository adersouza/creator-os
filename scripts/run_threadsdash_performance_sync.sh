#!/bin/bash
set -euo pipefail

if [ "$#" -gt 1 ] || { [ "$#" -eq 1 ] && [ "$1" != "--dry-run" ]; }; then
  echo "usage: $0 [--dry-run]" >&2
  exit 2
fi

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${CREATOR_OS_PERFORMANCE_SYNC_ENV:-$HOME/.creator-os/performance-sync.env}"

if [ "${XPC_SERVICE_NAME:-}" = "com.creator-os.threadsdash-performance-sync" ]; then
  for LOG in "$HOME/.creator-os/performance-sync.out.log" "$HOME/.creator-os/performance-sync.err.log"; do
    if [ -L "$LOG" ] || { [ -e "$LOG" ] && [ ! -f "$LOG" ]; }; then
      echo "unsafe performance-sync log path: $LOG" >&2
      exit 65
    fi
    : > "$LOG"
    chmod 600 "$LOG"
  done
fi

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
unset VIRTUAL_ENV PYTHONHOME PYTHONPATH

cd "$REPO_ROOT"
# shellcheck disable=SC1090
source "$ENV_FILE"

: "${CAMPAIGN_FACTORY_DB:?CAMPAIGN_FACTORY_DB is required}"
: "${REFERENCE_FACTORY_DB:?REFERENCE_FACTORY_DB is required}"
: "${CAMPAIGN_FACTORY_SYNC_CAMPAIGNS:?CAMPAIGN_FACTORY_SYNC_CAMPAIGNS is required}"

if [ ! -f "$CAMPAIGN_FACTORY_DB" ]; then
  echo "performance-sync database missing: $CAMPAIGN_FACTORY_DB" >&2
  exit 2
fi
if [ ! -f "$REFERENCE_FACTORY_DB" ]; then
  echo "performance-sync reference database missing: $REFERENCE_FACTORY_DB" >&2
  exit 2
fi

active_campaigns="$(python3 - "$CAMPAIGN_FACTORY_DB" <<'PY'
import json
import os
import sqlite3
import sys

campaigns = json.loads(os.environ["CAMPAIGN_FACTORY_SYNC_CAMPAIGNS"])
if not isinstance(campaigns, list) or not campaigns:
    raise SystemExit("performance-sync requires at least one configured campaign")
conn = sqlite3.connect(sys.argv[1])
try:
    active = []
    for campaign in campaigns:
        row = conn.execute(
            """SELECT COALESCE(cg.lifecycle_status, 'created')
               FROM campaigns c
               LEFT JOIN campaign_governance cg ON cg.campaign_id = c.id
               WHERE c.slug = ?""",
            (campaign,),
        ).fetchone()
        if row is None:
            raise SystemExit(f"performance-sync campaign missing: {campaign}")
        if row[0] not in {"cancelled", "archived"}:
            active.append(campaign)
    if not active:
        raise SystemExit("performance-sync has no active configured campaigns")
    print(json.dumps(active, separators=(",", ":")))
finally:
    conn.close()
PY
)"
export CAMPAIGN_FACTORY_SYNC_CAMPAIGNS="$active_campaigns"
exec python3 scripts/sync_threadsdash_performance.py "$@"

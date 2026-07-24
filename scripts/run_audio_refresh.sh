#!/bin/bash
# Machine-local weekly Audio Radar refresh entrypoint. Never schedules/publishes.
set -u
umask 077

ROOT="${CREATOR_OS_RUNTIME_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
ENV_FILE="${CREATOR_OS_AUDIO_REFRESH_ENV:-$HOME/.creator-os/generation.env}"
REPORT_DIR="${CREATOR_OS_AUDIO_REFRESH_REPORT_DIR:-$HOME/.creator-os/reports/audio-refresh}"
LATEST="$REPORT_DIR/latest-summary.json"

if [ ! -f "$ENV_FILE" ]; then
  echo "audio refresh private environment is missing" >&2
  exit 78
fi

# shellcheck disable=SC1090
source "$ENV_FILE"

: "${SOCIALCRAWL_API_KEY:?SOCIALCRAWL_API_KEY is required}"
: "${TIKLIVE_API_KEY:?TIKLIVE_API_KEY is required}"

REGION="${CREATOR_OS_AUDIO_REFRESH_REGION:-US}"
MAX_NEW="${CREATOR_OS_AUDIO_REFRESH_MAX_NEW:-20}"
MAX_ACTIVE="${CREATOR_OS_AUDIO_REFRESH_MAX_ACTIVE:-75}"

mkdir -p "$REPORT_DIR"
chmod 700 "$REPORT_DIR"
cd "$ROOT"

OUTPUT="$("$ROOT/scripts/creator-os" audio refresh \
  --region "$REGION" \
  --max-new "$MAX_NEW" \
  --max-active "$MAX_ACTIVE" \
  --apply)"
RC=$?

if [ "$RC" -ne 0 ]; then
  python3 - "$LATEST" "$RC" <<'PY'
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

path = Path(sys.argv[1])
temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
temporary.write_text(
    json.dumps(
        {
            "schema": "creator_os.audio_refresh_summary.v1",
            "status": "failed",
            "exitCode": int(sys.argv[2]),
            "completedAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)
temporary.chmod(0o600)
os.replace(temporary, path)
PY
  exit "$RC"
fi

SUMMARY_INPUT="$(mktemp "$REPORT_DIR/.audio-refresh-input.XXXXXX")"
printf '%s' "$OUTPUT" > "$SUMMARY_INPUT"
python3 - "$LATEST" "$SUMMARY_INPUT" <<'PY'
import json
import os
import sys
from pathlib import Path

receipt = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
summary = {
    "schema": "creator_os.audio_refresh_summary.v1",
    "runId": receipt.get("runId"),
    "status": receipt.get("status"),
    "completedAt": receipt.get("completedAt"),
    "sourceStatus": receipt.get("sourceStatus"),
    "counts": receipt.get("counts"),
    "credits": receipt.get("credits"),
    "receiptPath": receipt.get("receiptPath"),
}
path = Path(sys.argv[1])
temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
temporary.write_text(
    json.dumps(summary, separators=(",", ":"), sort_keys=True) + "\n",
    encoding="utf-8",
)
temporary.chmod(0o600)
os.replace(temporary, path)
print(json.dumps(summary, separators=(",", ":"), sort_keys=True))
PY
rm -f "$SUMMARY_INPUT"

#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/creator-os-promptfoo.XXXXXX")"
trap 'rm -rf "$TMP_DIR"' EXIT

export PROMPTFOO_CONFIG_DIR="$TMP_DIR/config"
export PROMPTFOO_CACHE_PATH="$TMP_DIR/cache"
export PROMPTFOO_LOG_DIR="$TMP_DIR/logs"
export PROMPTFOO_DISABLE_TELEMETRY=1
export PROMPTFOO_DISABLE_UPDATE=1
export PROMPTFOO_DISABLE_REMOTE_GENERATION=true
export PROMPTFOO_DISABLE_REDTEAM_REMOTE_GENERATION=true
export PROMPTFOO_DISABLE_SHARING=1
export PROMPTFOO_DISABLE_VAR_EXPANSION=1
export PROMPTFOO_SELF_HOSTED=1
export PROMPTFOO_CACHE_ENABLED=false
export PROMPTFOO_PYTHON="${PROMPTFOO_PYTHON:-$ROOT/.venv/bin/python}"
export FORCE_COLOR=0

if [[ ! -x "$PROMPTFOO_PYTHON" ]]; then
  echo "Promptfoo offline eval requires the synced workspace Python at $PROMPTFOO_PYTHON" >&2
  exit 2
fi

cd "$ROOT"
"$PROMPTFOO_PYTHON" evals/prompt_regressions/offline_guard.py
pnpm exec promptfoo eval \
  --config evals/prompt_regressions/promptfooconfig.json \
  --no-cache \
  --no-share \
  --output "$TMP_DIR/results.json"

#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROMPT_REGRESSION_PYTHON="${PROMPT_REGRESSION_PYTHON:-$ROOT/.venv/bin/python}"

if [[ ! -x "$PROMPT_REGRESSION_PYTHON" ]]; then
  echo "Offline prompt regressions require the synced workspace Python at $PROMPT_REGRESSION_PYTHON" >&2
  exit 2
fi

cd "$ROOT"
"$PROMPT_REGRESSION_PYTHON" evals/prompt_regressions/runner.py

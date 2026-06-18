#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TS_FIXTURE="$ROOT/packages/pipeline_contracts/__arch_guard_violation__.ts"
PY_FIXTURE="$ROOT/packages/pipeline_contracts/pipeline_contracts/__arch_guard_violation__.py"

cleanup() {
  rm -f "$TS_FIXTURE"
  rm -f "$PY_FIXTURE"
}
trap cleanup EXIT

cat > "$TS_FIXTURE" <<'FIXTURE'
import { runPipeline } from "../../apps/contentforge/lib/pipeline.js";

export const forbiddenArchitectureFixture = runPipeline;
FIXTURE

if (cd "$ROOT" && pnpm check:arch:ts >/tmp/creator-os-arch-guard-ts.log 2>&1); then
  cat /tmp/creator-os-arch-guard-ts.log
  echo "ERROR: dependency-cruiser did not reject pipeline_contracts -> app runtime import" >&2
  exit 1
fi

cleanup

cat > "$PY_FIXTURE" <<'FIXTURE'
from campaign_factory import core

VALUE = core.CampaignFactory
FIXTURE

if (cd "$ROOT" && python3 scripts/check-python-architecture-boundaries.py >/tmp/creator-os-arch-guard-py.log 2>&1); then
  cat /tmp/creator-os-arch-guard-py.log
  echo "ERROR: import-linter did not reject pipeline_contracts -> campaign_factory import" >&2
  exit 1
fi

echo "Architecture guard negative fixtures failed as expected."

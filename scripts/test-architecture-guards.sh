#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TS_FIXTURE="$ROOT/packages/pipeline_contracts/__arch_guard_violation__.ts"
PY_FIXTURE="$ROOT/packages/pipeline_contracts/pipeline_contracts/__arch_guard_violation__.py"
REEL_FACTORY_PY_FIXTURE="$ROOT/python_packages/reel_factory/__arch_guard_violation__.py"

cleanup() {
  rm -f "$TS_FIXTURE"
  rm -f "$PY_FIXTURE"
  rm -f "$REEL_FACTORY_PY_FIXTURE"
}
trap cleanup EXIT

# Positive controls: guards must pass on a clean tree. Without this, a guard
# that is broken (missing binary, bad config, crash) exits nonzero on every
# run and the negative fixtures below would "pass" for the wrong reason.
if ! (cd "$ROOT" && pnpm check:arch:ts >/tmp/creator-os-arch-guard-ts-clean.log 2>&1); then
  cat /tmp/creator-os-arch-guard-ts-clean.log
  echo "ERROR: dependency-cruiser failed on a clean tree; negative fixture results would be meaningless" >&2
  exit 1
fi

if ! (cd "$ROOT" && python3 scripts/check-python-architecture-boundaries.py >/tmp/creator-os-arch-guard-py-clean.log 2>&1); then
  cat /tmp/creator-os-arch-guard-py-clean.log
  echo "ERROR: python boundary checker failed on a clean tree; negative fixture results would be meaningless" >&2
  exit 1
fi

# Negative fixture 1: pipeline_contracts (TS) must not import app runtime.
cat > "$TS_FIXTURE" <<'FIXTURE'
import { runPipeline } from "../../apps/contentforge/lib/pipeline.js";

export const forbiddenArchitectureFixture = runPipeline;
FIXTURE

if (cd "$ROOT" && pnpm check:arch:ts >/tmp/creator-os-arch-guard-ts.log 2>&1); then
  cat /tmp/creator-os-arch-guard-ts.log
  echo "ERROR: dependency-cruiser did not reject pipeline_contracts -> app runtime import" >&2
  exit 1
fi

if ! grep -q "__arch_guard_violation__" /tmp/creator-os-arch-guard-ts.log; then
  cat /tmp/creator-os-arch-guard-ts.log
  echo "ERROR: dependency-cruiser failed, but not because of the injected fixture (log does not mention __arch_guard_violation__)" >&2
  exit 1
fi

cleanup

# Negative fixture 2: pipeline_contracts (py) must not import campaign_factory.
cat > "$PY_FIXTURE" <<'FIXTURE'
from campaign_factory import core

VALUE = core.CampaignFactory
FIXTURE

if (cd "$ROOT" && python3 scripts/check-python-architecture-boundaries.py >/tmp/creator-os-arch-guard-py.log 2>&1); then
  cat /tmp/creator-os-arch-guard-py.log
  echo "ERROR: boundary checker did not reject pipeline_contracts -> campaign_factory import" >&2
  exit 1
fi

if ! grep -q "pipeline_contracts must not import campaign_factory" /tmp/creator-os-arch-guard-py.log; then
  cat /tmp/creator-os-arch-guard-py.log
  echo "ERROR: boundary checker failed, but not with the expected pipeline_contracts violation message" >&2
  exit 1
fi

cleanup

# Negative fixture 3: reel_factory must not import campaign_factory.
cat > "$REEL_FACTORY_PY_FIXTURE" <<'FIXTURE'
from campaign_factory import core

VALUE = core.CampaignFactory
FIXTURE

if (cd "$ROOT" && python3 scripts/check-python-architecture-boundaries.py >/tmp/creator-os-arch-guard-reel-factory-py.log 2>&1); then
  cat /tmp/creator-os-arch-guard-reel-factory-py.log
  echo "ERROR: boundary checker did not reject reel_factory -> campaign_factory import" >&2
  exit 1
fi

if ! grep -q "reel_factory must not import campaign_factory" /tmp/creator-os-arch-guard-reel-factory-py.log; then
  cat /tmp/creator-os-arch-guard-reel-factory-py.log
  echo "ERROR: boundary checker failed, but not with the expected reel_factory violation message" >&2
  exit 1
fi

echo "Architecture guards: clean-tree positive controls passed and all negative fixtures were rejected for the expected reasons."

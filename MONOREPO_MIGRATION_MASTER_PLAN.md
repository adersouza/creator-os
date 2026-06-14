# Creator OS Monorepo Migration Master Plan

## Purpose

This document defines the long-term plan for making `creator-os` the unified source-of-truth repository for the full Creator OS pipeline.

The goal is not to dump every local folder into one giant repo. The goal is to create a professional monorepo that contains source code, contracts, tests, docs, and integration tooling while keeping runtime media, model weights, databases, uploads, and generated artifacts outside git.

## Executive Decision

Creator OS should move toward this model:

```text
creator-os = source-code monorepo and integration brain
split repos = temporary runtime baseline during migration
runtime data = ignored local folders, object storage, or external services
Graphify = codebase architecture/query layer for Codex
```

Do not treat `creator-os` as production runtime until it proves parity with the split repos through tests and staged operational checks.

## Current State

The active runtime pipeline still lives in split repos:

```text
/Users/aderdesouza/Developer/reel_factory
/Users/aderdesouza/Developer/campaign_factory
/Users/aderdesouza/Developer/contentforge
/Users/aderdesouza/Developer/ThreadsDashboard
/Users/aderdesouza/Developer/pipeline_contracts
/Users/aderdesouza/Developer/reference_factory
```

The `creator-os` repo already has the correct monorepo shape:

```text
creator-os/
├── apps/
│   ├── contentforge/
│   └── dashboard/
├── packages/
│   └── pipeline_contracts/
├── python_packages/
│   ├── campaign_factory/
│   ├── reel_factory/
│   └── reference_factory/
├── package.json
├── pnpm-workspace.yaml
├── pyproject.toml
└── uv.lock
```

The current branch is an import/repair branch, not the production source of truth:

```text
codex/creator-os-import-repair
```

## Target Architecture

### Desired Repository Layout

```text
creator-os/
├── apps/
│   ├── dashboard/                # ThreadsDashboard / Juno33 product app
│   └── contentforge/             # Variant/QC app
├── packages/
│   ├── pipeline_contracts/        # Shared schemas and validators
│   └── shared_tooling/            # Optional future shared scripts/types
├── python_packages/
│   ├── reel_factory/             # Creative generation
│   ├── campaign_factory/         # Operational control brain
│   └── reference_factory/        # Reference/audio/intelligence support
├── docs/
│   ├── architecture/
│   ├── runbooks/
│   └── decisions/
├── scripts/
│   ├── healthcheck/
│   ├── sync/
│   └── release/
├── tests/
│   └── integration/
├── AGENTS.md
├── README.md
├── ARCHITECTURE.md
├── pnpm-workspace.yaml
├── package.json
├── pyproject.toml
└── uv.lock
```

### Ownership Map

| Area | Canonical Owner In Monorepo | Notes |
|---|---|---|
| Creative still/video generation | `python_packages/reel_factory` | Direct reference-image path is active. Grok/Qwen/grid paths are legacy/experimental. |
| Variant generation and QC | `apps/contentforge` | Resumable variant-pack jobs and similarity/readiness checks live here. |
| Operational inventory/readiness | `python_packages/campaign_factory` | Campaign Factory remains the control brain. |
| Platform UI/execution | `apps/dashboard` | ThreadsDashboard/Juno33 owns drafts, scheduling, publishing UI, analytics, smart links. |
| Shared schemas | `packages/pipeline_contracts` | Must become the only source of truth for cross-repo contracts. |
| Reference/audio intelligence | `python_packages/reference_factory` | Source/reference analysis and audio catalog support. |
| Architecture/codebase map | Graphify output | Generated locally, not committed by default. |

## Non-Negotiable Boundaries

### Keep In Git

Commit these:

```text
source code
tests
schema files
TypeScript contract exports
Python package metadata
docs
runbooks
small deterministic fixtures
integration test harnesses
AGENTS.md / Codex instructions
```

### Keep Out Of Git

Do not commit these:

```text
node_modules/
.venv/
.next/
dist/
build/
coverage/
__pycache__/
.pytest_cache/
.ruff_cache/
.mypy_cache/
campaign_factory.db
*.sqlite
*.sqlite-shm
*.sqlite-wal
reel_factory/models/
reel_factory/00_source_videos/
reel_factory/02_processed/
reel_factory/output/
campaign_factory/campaigns/
campaign_factory/tmp/
contentforge/output/
contentforge/uploads/
graphify-out/
local proof images/videos
Higgsfield/Kling paid generation outputs
```

### Runtime Data Strategy

Runtime state should be addressed with one of these patterns:

```text
local ignored folder
environment variable path
object storage
database
artifact bucket
small fixture copy for tests
```

If a file is needed for a test, create a small deterministic fixture. Do not commit full production media just to make a test pass.

## Migration Phases

### Phase 0: Freeze The Baseline

Goal: Know exactly what is trusted before migration.

Actions:

1. Keep split repos as the deployable runtime baseline.
2. Record current branches and test results for:
   - `reel_factory`
   - `campaign_factory`
   - `contentforge`
   - `ThreadsDashboard`
   - `pipeline_contracts`
   - `reference_factory`
3. Do not delete or archive split repos yet.
4. Do not change scheduling, publishing, QStash, account health, metrics sync, or production inventory behavior during monorepo migration.

Exit criteria:

```text
all split-repo test suites pass
all current dirty changes are either committed or intentionally documented
creator-os import branch is up to date with repaired split-repo heads
```

### Phase 1: Make Contracts Canonical

Goal: `packages/pipeline_contracts` becomes the only source of truth for shared payload schemas.

Actions:

1. Move all schema work into `packages/pipeline_contracts`.
2. Keep root compatibility copies only if tests require them, and add a sync check.
3. Update Dashboard/ContentForge/Campaign Factory to consume the package contract copy.
4. Remove stale vendored schema snapshots only after consumer tests prove parity.

Required checks:

```bash
cd /Users/aderdesouza/Developer/creator-os
uv run pytest packages/pipeline_contracts/tests
pnpm --filter juno33 test
pnpm --filter contentforge test
```

Exit criteria:

```text
contract schema copies are identical or eliminated
contract sync check passes
dashboard and campaign payload tests pass
no --no-verify needed for contract hooks
```

### Phase 2: Promote JavaScript Apps

Goal: `apps/dashboard` and `apps/contentforge` run cleanly under the monorepo `pnpm` workspace.

Actions:

1. Keep `apps/dashboard` as the ThreadsDashboard source tree.
2. Keep `apps/contentforge` as the ContentForge source tree.
3. Remove committed build output and local uploads from the monorepo.
4. Ensure each app can run tests from both its app folder and root workspace commands.
5. Keep smart-link hardening and UI rebuild changes as separate commits.

Required checks:

```bash
cd /Users/aderdesouza/Developer/creator-os
pnpm install --frozen-lockfile
pnpm --filter contentforge test
pnpm --filter juno33 test
pnpm --filter juno33 typecheck
```

Exit criteria:

```text
Dashboard tests pass
ContentForge tests pass
contract snapshot checks pass
no output/uploads/build artifacts tracked
```

### Phase 3: Promote Python Packages

Goal: Python packages run under the monorepo `uv` workspace without losing their split-repo behavior.

Actions:

1. Keep Python packages under `python_packages/`.
2. Make imports work from monorepo root via `pyproject.toml` and `uv`.
3. Keep package-specific tests intact.
4. Preserve local split-repo CLI compatibility during transition.
5. Ensure large data folders are ignored.

Required checks:

```bash
cd /Users/aderdesouza/Developer/creator-os
uv sync --all-extras --all-packages
uv run pytest python_packages/reel_factory/tests
uv run pytest python_packages/campaign_factory/tests
uv run pytest python_packages/reference_factory/tests
uv run python -m compileall python_packages
```

Exit criteria:

```text
Reel Factory tests pass
Campaign Factory tests pass
Reference Factory tests pass
compileall passes
no model/media/database folders tracked
```

### Phase 4: Add Cross-Pipeline Acceptance Tests

Goal: Prove the monorepo represents the actual Creator OS pipeline, not just copied folders.

Add integration tests for:

```text
reference input contract
direct reference-image still contract
Kling motion prompt contract
ContentForge audit/readiness contract
Campaign Factory publishability/readiness contract
handoff manifest v2
ThreadDash-compatible draft payload
metrics/performance sync contract
```

Do not run live scheduling or publishing in CI.

Required checks:

```bash
cd /Users/aderdesouza/Developer/creator-os
uv run pytest tests/integration
pnpm -r --if-present test
```

Exit criteria:

```text
asset -> readiness -> manifest -> draft payload dry-run passes
no schedule/export/publish happens in tests
all integration tests are deterministic
```

### Phase 5: Make Graphify The Architecture Brain

Goal: Codex can ask architecture questions from one graph.

Actions:

1. Keep Graphify installed as a Codex tool/skill, not as Creator OS runtime dependency.
2. Generate Graphify output locally when needed.
3. Do not commit `graphify-out/` unless a specific lightweight artifact is intentionally approved.
4. Use Graphify for architecture audits, ownership checks, and dependency questions.

Recommended commands:

```bash
cd /Users/aderdesouza/Developer/creator-os
graphify extract . --no-cluster
graphify query "What owns schedule-safe inventory?"
graphify query "How does Campaign Factory hand off to ThreadsDashboard?"
graphify path "CampaignFactory" "ThreadsDashboard"
```

Exit criteria:

```text
Graphify can answer cross-package ownership questions
Graphify output is ignored by default
Codex AGENTS.md explains when to use Graphify
```

### Phase 6: Promote Monorepo To Source Of Truth

Goal: Stop treating split repos as primary.

Actions:

1. Cut a release candidate branch in `creator-os`.
2. Run all monorepo tests.
3. Compare split repo heads against monorepo package heads.
4. Freeze split repos temporarily.
5. Decide whether split repos become:
   - archived read-only mirrors, or
   - generated deploy mirrors from monorepo.

Exit criteria:

```text
monorepo tests match or exceed split repo tests
deployment path is documented
operator runbooks point to creator-os
split repo drift risk is eliminated
```

## Commit Strategy

Use small commits grouped by ownership:

```text
contracts canonicalization
dashboard workspace repair
contentforge workspace repair
reel factory workspace repair
campaign factory workspace repair
reference factory workspace repair
integration tests
docs/runbooks
gitignore/runtime-data cleanup
```

Do not combine these in one commit:

```text
smart-link behavior changes
UI redesign/shadcn rebuild
pipeline contracts
runtime generation changes
monorepo housekeeping
```

## Branch Strategy

Suggested branches:

```text
codex/creator-os-monorepo-contracts
codex/creator-os-monorepo-js-apps
codex/creator-os-monorepo-python-packages
codex/creator-os-monorepo-integration-tests
codex/creator-os-monorepo-docs
```

Keep the current branch as a staging/import repair branch until the above phases land:

```text
codex/creator-os-import-repair
```

## Required `.gitignore` Policy

The monorepo root `.gitignore` must protect these categories:

```gitignore
# dependencies
node_modules/
.venv/

# build/test outputs
.next/
dist/
build/
coverage/
__pycache__/
.pytest_cache/
.ruff_cache/
.mypy_cache/

# databases
*.sqlite
*.sqlite-shm
*.sqlite-wal
*.db

# media/model/runtime data
**/models/
**/00_source_videos/
**/02_processed/
**/output/
**/uploads/
**/campaigns/
**/tmp/

# local graph/intelligence outputs
graphify-out/

# OS/editor junk
.DS_Store
```

If a package needs a small fixture under one of those names, allowlist that exact fixture path.

## CI Strategy

The final CI should run in layers:

```text
contracts
python package tests
typescript app tests
integration dry-runs
lint/typecheck
artifact hygiene
```

Suggested root commands:

```bash
pnpm -r --if-present test
pnpm -r --if-present typecheck
uv run pytest
uv run python -m compileall python_packages packages
git diff --check
```

Add an artifact hygiene check:

```bash
git ls-files | grep -E '(^|/)(node_modules|\\.venv|\\.next|dist|build|output|uploads|campaigns|models|graphify-out)/' && exit 1
git ls-files | grep -E '\\.(mp4|mov|sqlite|sqlite-shm|sqlite-wal|db)$' && exit 1
```

## Runtime Deployment Strategy

Do not switch deployment all at once.

Recommended order:

1. Keep current deploys from split repos.
2. Run monorepo CI in parallel.
3. Promote `apps/contentforge` deployment from monorepo first.
4. Promote `apps/dashboard` deployment after contract sync is stable.
5. Promote Python package release/dev workflows after local CLI parity is proven.
6. Archive split repos only after successful staged production operations.

## Operational Proof Required Before Full Promotion

Monorepo source-of-truth is not just a code organization decision. It must preserve operational proof.

Required evidence:

```text
Reel Factory direct-reference still path works
Kling motion prompt path works
ContentForge variant-pack jobs pass
Campaign Factory readiness/publishability passes
ThreadsDashboard draft/schedule/publish tests pass
25-account readiness remains certified
50-account readiness blocker remains explicit if inventory is short
no scheduling/publishing behavior changes during migration
```

## What Not To Do

Do not:

```text
commit model weights
commit production videos
commit Campaign Factory database files
commit ContentForge uploads/output
merge dirty split repos blindly
delete split repos before monorepo parity
mix smart-link hardening with UI rebuilds
use monorepo migration to change scheduling/publishing/account-health behavior
add new reports or planning layers as part of migration
```

## Decision Gate

Creator OS can become the official monorepo source of truth only when this JSON is true:

```json
{
  "contractsCanonical": true,
  "dashboardTestsPass": true,
  "contentForgeTestsPass": true,
  "reelFactoryTestsPass": true,
  "campaignFactoryTestsPass": true,
  "referenceFactoryTestsPass": true,
  "integrationDryRunPasses": true,
  "runtimeArtifactsIgnored": true,
  "splitRepoParityVerified": true,
  "schedulingBehaviorChanged": false,
  "publishingBehaviorChanged": false,
  "accountHealthBehaviorChanged": false,
  "metricsSyncBehaviorChanged": false
}
```

Until then, the split repos remain the trusted production baseline.

## Recommended Next Step

Start with Phase 1:

```text
make pipeline_contracts canonical inside creator-os
prove Dashboard and Campaign Factory consume the same contract package
remove or sync stale schema snapshots
```

This is the highest-leverage first move because every other migration depends on contract consistency.

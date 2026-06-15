# Creator OS Monorepo Deployment Promotion

`creator-os/main` now has monorepo source gates through Phase 4, but the split
repos remain the trusted runtime baseline until promotion is explicit.

## Current Promotion Status

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
  "splitRepoBranchesMerged": true,
  "creatorOsMainMerged": true,
  "stagedAcceptanceAgainstCopiedRuntimeDb": true,
  "currentCertifiedStage": 25,
  "nextStageTarget": 50,
  "productionRuntimePromoted": false
}
```

## Latest Non-Mutating Staged Acceptance

On June 14, 2026, the monorepo Campaign Factory CLI was run against a copied
Campaign Factory SQLite database:

```text
/Users/aderdesouza/Developer/campaign_factory/campaign_factory.sqlite
→ /tmp/creator_os_campaign_factory_runtime_check.sqlite
```

This avoided mutating the split runtime database while proving the monorepo code
path against current runtime-like state.

```json
{
  "currentCertifiedStage": 25,
  "nextStageTarget": 50,
  "readyForNextStage": false,
  "eligibleAccounts": 70,
  "restrictedAccounts": 0,
  "warmingAccounts": 0,
  "availableInventory": 273,
  "wouldWrite": false
}
```

The focused 25-account Reel gate also passed from the copied database:

```json
{
  "accountTarget": 25,
  "contentSurface": "reel",
  "requiredInventory": 225,
  "availableInventory": 270,
  "eligibleAccounts": 70,
  "acceptancePassed": true,
  "blockingReasons": [],
  "wouldWrite": false
}
```

The 50-account stage remains blocked only by inventory:

```json
{
  "accountTarget": 50,
  "requiredInventory": 450,
  "availableInventory": 273,
  "acceptancePassed": false,
  "blockingReasons": ["inventory_buffer_not_maintained"],
  "wouldWrite": false
}
```

## CI Gates Required Before Promotion

The monorepo CI workflow at `.github/workflows/monorepo-ci.yml` runs:

- `pnpm check:contracts`
- `pnpm --filter contentforge test`
- `pnpm --filter juno33 test`
- `pnpm --filter juno33 typecheck`
- `uv sync --all-extras --all-packages`
- `uv run pytest packages/pipeline_contracts/tests`
- `uv run pytest python_packages/campaign_factory/tests`
- `uv run pytest python_packages/reel_factory/tests`
- `uv run pytest python_packages/reference_factory/tests`
- `uv run pytest tests/integration`
- Python `compileall`
- git whitespace and runtime-artifact hygiene checks

## Deployment Order

Do not switch all runtime surfaces at once.

1. Keep all current deployments running from split repos.
2. Run monorepo CI in parallel on every migration branch.
3. Promote `apps/contentforge` first because it has no publishing authority.
4. Promote `apps/dashboard` only after contract sync and publish preflight tests pass in CI.
5. Promote Python package workflows after CLI parity is documented for each package.
6. Keep split repos available as rollback mirrors until staged operations prove no drift.

## Production Promotion Checklist

Do not promote the monorepo runtime until every item below is checked against
the current `creator-os/main` commit.

### ContentForge

- Run the monorepo ContentForge test suite.
- Run a non-mutating variant-pack dry-run against fixtures.
- Confirm no Campaign Factory commits occur on timeout or failed variant-pack
  jobs.
- Confirm the split `contentforge` repo is still available as rollback mirror.

### Dashboard

- Run contract sync, unit tests, typecheck, and visual regression.
- Run publish preflight tests from monorepo Dashboard code.
- Confirm cron entries in `apps/dashboard/vercel.json` are reviewed before any
  Vercel production project points at the monorepo.
- Confirm split `ThreadsDashboard` remains rollback mirror. The active split
  ThreadsDashboard checkout is out of scope while another Codex instance is
  working on frontend/autoposter changes.

### Python CLIs

- Prove Reel Factory direct-reference dry-run parity.
- Prove Campaign Factory readiness and publishability dry-run parity.
- Prove Reference Factory support command parity.
- Run the non-mutating staged operational dry-run below from the monorepo path.

### Rollback

- Keep split repos read-only and deployable for at least one clean operating
  cycle after promotion.
- Document the deployed commit SHA for each promoted surface.
- Keep environment variables and secrets unchanged during the first promotion.
- Roll back by repointing deploy configuration to the prior split repo SHA; do
  not patch production behavior during rollback.

## Required Staged Operational Proof

Before production runtime promotion, run a staged dry-run using non-production
state or a disposable fixture database:

```text
reference fixture
→ Reel Factory contract fixture
→ Campaign Factory readiness/publishability dry-run
→ ContentForge variant/readiness dry-run
→ Campaign Factory handoff manifest
→ Dashboard draft payload/preflight validation
→ stop before export/schedule/publish
```

The staged proof must show:

- no schedules created
- no posts published
- no drafts exported to production
- no metrics or account-health mutation
- no generated media committed
- failure blockers are explicit when any gate fails

## Promotion Blockers Remaining

- Deployment configuration still points at split repos.
- Production runtime has not been switched to the monorepo.
- Dashboard production deployment must not be moved blindly because
  `apps/dashboard/vercel.json` includes cron entries for scheduler and publish
  workers.
- The next scale gate is 50 accounts, blocked by inventory buffer
  (`273 available` vs `450 required` in the latest copied-DB check).

Until those are resolved, `creator-os` is the integration candidate, not the
production runtime source of truth.

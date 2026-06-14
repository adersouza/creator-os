# Creator OS Monorepo Deployment Promotion

`creator-os` now has local monorepo gates through Phase 4, but the split repos
remain the trusted runtime baseline until promotion is explicit.

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
  "splitRepoBranchesMerged": false,
  "productionRuntimePromoted": false
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

- Split repo cleanup branches are clean and pushed, but most are not merged to
  their runtime `main` branches yet.
- Deployment configuration still points at split repos.
- No live/staged operational run has been approved from the monorepo runtime.

Until those are resolved, `creator-os` is the integration candidate, not the
production runtime source of truth.

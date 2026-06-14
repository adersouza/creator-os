# Creator OS Monorepo Phase 4 Acceptance

Phase 4 adds deterministic cross-pipeline acceptance tests for the monorepo.
The tests prove contract compatibility only. They do not schedule, publish,
export drafts, generate media, sync metrics, mutate account health, or write
runtime inventory.

## Acceptance Gate

Run from the monorepo root:

```bash
pnpm check:contracts
pnpm check:integration
```

The integration suite lives in `tests/integration/` and verifies:

- canonical `packages/pipeline_contracts` schemas match every compatibility mirror
- Reel Factory still-image and Kling motion prompt contracts validate before Campaign Factory handoff
- ContentForge variant-pack output fields map into Campaign Factory variant lineage
- Campaign Factory handoff manifests validate against ThreadDash-compatible draft payload contracts
- Handoff manifest v2 is represented in the shared draft payload schema for non-Reel surfaces
- fixtures use logical `fixture://` references instead of real media, uploads, databases, or model weights

## What Phase 4 Does Not Prove

Phase 4 does not make `creator-os` the production runtime source of truth.
The split repos remain the trusted runtime baseline until these items are
completed:

- full monorepo CI runs the contract, JS, Python, integration, lint, typecheck, and artifact hygiene gates
- split repo heads are compared against monorepo package heads after the current repair branches are merged
- deployment paths are documented for Dashboard, ContentForge, and Python package workflows
- staged operational checks confirm no scheduling, publishing, account-health, metrics, or inventory behavior changed
- Graphify architecture output remains local and ignored unless a specific lightweight artifact is approved

## Current Promotion Rule

`creator-os` can replace the split repos only after the decision gate in
`MONOREPO_MIGRATION_MASTER_PLAN.md` is true. Until then, monorepo tests improve
confidence, but runtime operations should continue from the verified split repos.

# Creator OS Monorepo Phase 4 Acceptance (Completed)

Phase 4 established the deterministic cross-pipeline acceptance tests now
retained in `tests/integration/`. This page is historical context for that test
layer, not a current runtime-promotion checklist. Current promotion policy is
[`monorepo_deployment_promotion.md`](./monorepo_deployment_promotion.md).

The tests prove source and contract compatibility only. They do not schedule,
publish, export production drafts, perform paid generation, sync live metrics,
mutate account health, or write runtime inventory.

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

Phase 4 acceptance still does not prove:

- that a merged Creator OS commit was promoted to the pinned runtime checkout;
- that a paid provider is configured, healthy, or authorized;
- that ThreadsDashboard accepted, scheduled, or published a draft;
- that QStash delivered a publish action;
- that Instagram returned publication identity or real metrics;
- that Graphify output is current or approved for commit.

## Current Promotion Rule

Creator OS is now the canonical integration source. The pinned
`creator-os-runtime` checkout changes only through the explicit source-to-runtime
procedure in `monorepo_deployment_promotion.md`. ThreadsDashboard remains an
external product repository. Historical component split repositories are not
current runtime instructions or automatic rollback targets.

The original phased migration plan remains archived at
`docs/archive/MONOREPO_MIGRATION_MASTER_PLAN.md`.

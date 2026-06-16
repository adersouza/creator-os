# Merge Plan - 2026-06-16

Integration merges performed by this resumed run are recorded below with proof.

## Integration Branch Registry

| Repo | Integration branch | Current branch at inventory | Inventory HEAD | Required pre-merge action |
| --- | --- | --- | --- | --- |
| `creator-os` | `main` | `codex/mirror-parity-gate` | merged branch tip `e73c5bc9b117fdeabba09f3aa84fa79ac7cfd2a9` | merged to `main` as `b6ca0c66ed41d1c8134645cab0de1788f2526edf`; ancestor proof exit 0 |
| `ThreadsDashboard` | `main` | `codex/autoposter-hardening` | merged branch tip `e77466edecd1891962b7ebb52047960b1c284e81` | merged to `main` as `7c3757574dd1b3d7b6d0008f1902d1e157c41577`; ancestor proof exit 0 |
| `ThreadsDashboard` | `main` | `codex/audit-port` | branch tip `22a9476890dfebfd8200c15b602c9b7d2139e1c5` | pre-merge tests green; merge pending from `main@7c3757574dd1b3d7b6d0008f1902d1e157c41577` |
| `campaign_factory` | `main` | `codex/campaign-caption-inventory` | `99f27208c` | Rerun pytest if branch changes; record `main` pre-merge SHA |
| `reel_factory` | `main` | `codex/split-review-truth` | `4bad3acab` | Push branch upstream if needed; record `main` pre-merge SHA |
| `pipeline_contracts` | `main` | `codex/campaign-draft-contract-sync` | `e45374abe` | Rerun pytest if branch changes; record `main` pre-merge SHA |
| `contentforge` | `main` | `main` | `47e1293ce` | Pending only if future changes are made |
| `reference_factory` | `main` | inventory `main`; fix branch `codex/reference-test-deps` | inventory `2cf59f2a7`; fix branch `2ea2a7f` | Red pytest dependency baseline fixed and pushed; record `main` pre-merge SHA before ordered repo-maturity merge |

## Required Merge Record Format

For every actual merge, append:

- Repo:
- Branch:
- Branch tip SHA:
- Pre-merge integration SHA:
- Merge SHA:
- Rollback command:
- Ancestor proof command and result:
- Required test evidence:
- TD deploy note, when repo is `ThreadsDashboard`:

## Inventory Ancestry State

- `creator-os`: `codex/mirror-parity-gate@e73c5bc9b117fdeabba09f3aa84fa79ac7cfd2a9` is an ancestor of `main` after merge commit `b6ca0c66ed41d1c8134645cab0de1788f2526edf`.
- `ThreadsDashboard`: `codex/autoposter-hardening@e77466edecd1891962b7ebb52047960b1c284e81` is an ancestor of `main` after merge commit `7c3757574dd1b3d7b6d0008f1902d1e157c41577`.
- `ThreadsDashboard`: `codex/audit-port@22a9476890dfebfd8200c15b602c9b7d2139e1c5` is green and pending merge to `main@7c3757574dd1b3d7b6d0008f1902d1e157c41577`.
- `campaign_factory`: `codex/campaign-caption-inventory@99f27208c` is 1 behind and 1 ahead of `main`; merge pending.
- `reel_factory`: `codex/split-review-truth@4bad3acab` is 2 ahead of `main`; merge pending.
- `pipeline_contracts`: `codex/campaign-draft-contract-sync@e45374abe` is 1 behind and 1 ahead of `main`; merge pending.

## Current Red Gates Blocking Merges

- None currently after `reference_factory/codex/reference-test-deps@2ea2a7f` fixed the `httpx2` test extra and reran 84 passing tests. Merges still require fresh pre-merge gates.

## Planned Merge Records

### creator-os WS1 Mirror Parity

- Repo: `creator-os`
- Branch: `codex/mirror-parity-gate`
- Branch tip SHA: `e73c5bc9b117fdeabba09f3aa84fa79ac7cfd2a9`
- Pre-merge integration SHA: `c1b70250c26845a8c5629dee7b87d5e3b6d8de28`
- Merge SHA: `b6ca0c66ed41d1c8134645cab0de1788f2526edf`
- Rollback command: `git revert -m 1 b6ca0c66ed41d1c8134645cab0de1788f2526edf`
- Ancestor proof command and result: `git merge-base --is-ancestor e73c5bc9b117fdeabba09f3aa84fa79ac7cfd2a9 main; echo $?` returned `0`.
- Pre-merge required test evidence:
  - `pnpm check:mirror-parity` pass at `a566e25492202aa9bdf18633fe8aedca8d6a4089`; pre-merge record commit was docs-only.
  - `pnpm check:contracts` pass.
  - `pnpm check:artifacts` pass.
  - `env UV_CACHE_DIR=/private/tmp/codex-uv-cache pnpm check:arch` pass.
  - `pnpm --filter juno33 typecheck` pass.
  - `pnpm --filter juno33 test` pass: 359 files passed, 1 skipped; 4701 passed, 1 skipped, 3 todo.
  - `env UV_CACHE_DIR=/private/tmp/codex-uv-cache uv run pytest packages/pipeline_contracts/tests python_packages/campaign_factory/tests python_packages/reel_factory/tests python_packages/reference_factory/tests tests/integration` pass: 795 passed, 48 warnings.

### ThreadsDashboard Step B Autoposter Hardening

- Repo: `ThreadsDashboard`
- Branch: `codex/autoposter-hardening`
- Branch tip SHA: `e77466edecd1891962b7ebb52047960b1c284e81`
- Pre-merge integration SHA: `b3d015e5e470e6c157b60d90ebff4c0b51d21897`
- Merge SHA: `7c3757574dd1b3d7b6d0008f1902d1e157c41577`
- Rollback command: `git revert -m 1 7c3757574dd1b3d7b6d0008f1902d1e157c41577`
- Ancestor proof command and result: `git merge-base --is-ancestor e77466edecd1891962b7ebb52047960b1c284e81 main; echo $?` returned `0`.
- Pre-merge required test evidence:
  - `git diff --check` pass.
  - `npm run typecheck` pass.
  - `npm run compat:check` pass.
  - `npm run test` pass: 359 files passed, 1 skipped; 4701 passed, 1 skipped, 3 todo.
  - `npm run build` pass.
  - `npm run test:e2e:critical` pass with local `npm run dev` server: 5 passed, 1 skipped.
  - `graphify update .` pass.
  - Reconciliation commit `e77466edecd1891962b7ebb52047960b1c284e81` pushed to `origin/codex/autoposter-hardening`.
- TD deploy note: pushed `ThreadsDashboard/main` from `b3d015e5e470e6c157b60d90ebff4c0b51d21897` to `7c3757574dd1b3d7b6d0008f1902d1e157c41577`; no Vercel relink or deploy-config change was made.

### ThreadsDashboard Step C Campaign Factory Draft Ingest

- Repo: `ThreadsDashboard`
- Branch: `codex/audit-port`
- Branch tip SHA: `22a9476890dfebfd8200c15b602c9b7d2139e1c5`
- Pre-merge integration SHA: `7c3757574dd1b3d7b6d0008f1902d1e157c41577`
- Merge SHA: pending
- Rollback command: `git revert -m 1 <step-c-merge-sha>`
- Ancestor proof command and result: pending.
- Pre-merge required test evidence:
  - `git diff --check` pass.
  - `npm test -- tests/unit/campaignFactoryDraftIngest.test.ts` pass: 1 file passed; 10 passed.
  - `npm test -- tests/unit/mcpApiCoverage.test.ts tests/unit/campaignFactoryDraftIngest.test.ts` pass: 2 files passed; 12 passed.
  - `npm run typecheck` pass.
  - `npm run compat:check` pass.
  - `npm run test` pass: 360 files passed, 1 skipped; 4711 passed, 1 skipped, 3 todo.
  - `npm run build` pass.
  - `npm run test:e2e:critical` pass with local `npm run dev` server: 1 passed, 5 skipped.
  - `graphify update .` pass.
  - Branch commit `22a9476890dfebfd8200c15b602c9b7d2139e1c5` pushed to `origin/codex/audit-port`.
- TD deploy note: pending merge to `ThreadsDashboard/main`; no Vercel relink or deploy-config change was made.

## Deferred Owner-Only Work

- Secret rotation and git-history purge.
- 50/100/200 scale proof and QStash outage/reconciliation-drain proof.
- Account graph certification.

# Merge Plan - 2026-06-16

Integration merges performed by this resumed run are recorded below with proof.

## Integration Branch Registry

| Repo | Integration branch | Current branch at inventory | Inventory HEAD | Required pre-merge action |
| --- | --- | --- | --- | --- |
| `creator-os` | `main` | `codex/mirror-parity-gate` | merged branch tip `e73c5bc9b117fdeabba09f3aa84fa79ac7cfd2a9` | merged to `main` as `b6ca0c66ed41d1c8134645cab0de1788f2526edf`; ancestor proof exit 0 |
| `ThreadsDashboard` | `main` | `codex/autoposter-hardening` | merged branch tip `e77466edecd1891962b7ebb52047960b1c284e81` | merged to `main` as `7c3757574dd1b3d7b6d0008f1902d1e157c41577`; ancestor proof exit 0 |
| `ThreadsDashboard` | `main` | `codex/audit-port` | branch tip `22a9476890dfebfd8200c15b602c9b7d2139e1c5` | merged to `main` as `bac25a9d213f86d837e07a94559a78f935abffd9`; ancestor proof exit 0 |
| `campaign_factory` | `main` | `codex/campaign-caption-inventory` | branch tip `99f27208c8664d488fd666e81f685ce31eebf85f` | merged to `main` as `c0912e4cf44fd40216858f75f89d8980a73c1400`; ancestor proof exit 0 |
| `reel_factory` | `main` | `codex/split-review-truth` | branch tip `4bad3acabcef1b128f02f15f16869b28e7830589` | merged to `main` as `49584b77114b6308597a6d9303bf7e8edcfd4c1d`; ancestor proof exit 0; `codex/review-truth-port@9b7f61afe76bceaa46bb3b93100730fe06620607` is red and not mergeable |
| `pipeline_contracts` | `main` | `codex/campaign-draft-contract-sync` | branch tip `e45374abeb1c57aa28432b00c0c68ed45328725a` | merged to `main` as `b835f52b5eaf4d01652c5e40d13d8063d235bdbf`; ancestor proof exit 0 |
| `pipeline_contracts` | `main` | `codex/canonical-campaign-draft-schema-sync` | branch tip `3f6e43a2ede15fbbb9bef854e45ee0173947e5bd` | pre-merge tests green; merge pending from `main@b835f52b5eaf4d01652c5e40d13d8063d235bdbf` |
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
- `ThreadsDashboard`: `codex/audit-port@22a9476890dfebfd8200c15b602c9b7d2139e1c5` is an ancestor of `main` after merge commit `bac25a9d213f86d837e07a94559a78f935abffd9`.
- `campaign_factory`: `codex/campaign-caption-inventory@99f27208c8664d488fd666e81f685ce31eebf85f` is an ancestor of `main` after merge commit `c0912e4cf44fd40216858f75f89d8980a73c1400`.
- `reel_factory`: `codex/split-review-truth@4bad3acabcef1b128f02f15f16869b28e7830589` is an ancestor of `main` after merge commit `49584b77114b6308597a6d9303bf7e8edcfd4c1d`.
- `pipeline_contracts`: `codex/campaign-draft-contract-sync@e45374abeb1c57aa28432b00c0c68ed45328725a` is an ancestor of `main` after merge commit `b835f52b5eaf4d01652c5e40d13d8063d235bdbf`.
- `pipeline_contracts`: `codex/canonical-campaign-draft-schema-sync@3f6e43a2ede15fbbb9bef854e45ee0173947e5bd` is green and pending merge to `main@b835f52b5eaf4d01652c5e40d13d8063d235bdbf`.

## Current Red Gates Blocking Merges

- `reel_factory/codex/review-truth-port@9b7f61afe76bceaa46bb3b93100730fe06620607` is not mergeable in this fresh run: `env UV_CACHE_DIR=/private/tmp/codex-uv-cache uv run --extra dev python -m pytest tests` collected 113 items then failed with 4 collection errors because `pilmoji` is missing. The green `codex/split-review-truth@4bad3acabcef1b128f02f15f16869b28e7830589` branch is a superset and includes the dependency/portability fixes.
- `reference_factory/codex/reference-test-deps@2ea2a7f` fixed the `httpx2` test extra and reran 84 passing tests. Merge still requires fresh pre-merge gates.

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
- Merge SHA: `bac25a9d213f86d837e07a94559a78f935abffd9`
- Rollback command: `git revert -m 1 bac25a9d213f86d837e07a94559a78f935abffd9`
- Ancestor proof command and result: `git merge-base --is-ancestor 22a9476890dfebfd8200c15b602c9b7d2139e1c5 main; echo $?` returned `0`.
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
- TD deploy note: pushed `ThreadsDashboard/main` from `7c3757574dd1b3d7b6d0008f1902d1e157c41577` to `bac25a9d213f86d837e07a94559a78f935abffd9`; no Vercel relink or deploy-config change was made.

### campaign_factory Step D Caption Inventory

- Repo: `campaign_factory`
- Branch: `codex/campaign-caption-inventory`
- Branch tip SHA: `99f27208c8664d488fd666e81f685ce31eebf85f`
- Pre-merge integration SHA: `ba8768f9daeb0f8b42ac87bd3a0a7c0f9503fda3`
- Merge SHA: `c0912e4cf44fd40216858f75f89d8980a73c1400`
- Rollback command: `git revert -m 1 c0912e4cf44fd40216858f75f89d8980a73c1400`
- Ancestor proof command and result: `git merge-base --is-ancestor 99f27208c8664d488fd666e81f685ce31eebf85f main; echo $?` returned `0`.
- Pre-merge required test evidence:
  - `git diff --check` pass.
  - `env UV_CACHE_DIR=/private/tmp/codex-uv-cache uv run --extra dev python -m pytest tests` pass: 383 passed.

### reel_factory Step D Review Truth

- Repo: `reel_factory`
- Branch: `codex/split-review-truth`
- Branch tip SHA: `4bad3acabcef1b128f02f15f16869b28e7830589`
- Pre-merge integration SHA: `cc8845be5915484e7fe81d5c419f76d007ddadb3`
- Merge SHA: `49584b77114b6308597a6d9303bf7e8edcfd4c1d`
- Rollback command: `git revert -m 1 49584b77114b6308597a6d9303bf7e8edcfd4c1d`
- Ancestor proof command and result: `git merge-base --is-ancestor 4bad3acabcef1b128f02f15f16869b28e7830589 main; echo $?` returned `0`.
- Pre-merge required test evidence:
  - `git diff --check` pass.
  - `env UV_CACHE_DIR=/private/tmp/codex-uv-cache uv run --extra dev python -m pytest tests` pass: 307 passed, 48 warnings.
- Divergence note: `codex/review-truth-port@9b7f61afe76bceaa46bb3b93100730fe06620607` was not merged because the fresh suite is red with 4 collection errors from missing `pilmoji`; `codex/split-review-truth@4bad3acabcef1b128f02f15f16869b28e7830589` contains the review-truth work plus producer/dependency/portability fixes and is green.

### pipeline_contracts Step D Campaign Draft Contract Sync

- Repo: `pipeline_contracts`
- Branch: `codex/campaign-draft-contract-sync`
- Branch tip SHA: `e45374abeb1c57aa28432b00c0c68ed45328725a`
- Pre-merge integration SHA: `c84faa7d478b78cb227eeed3a27f53aedd480ea6`
- Merge SHA: `b835f52b5eaf4d01652c5e40d13d8063d235bdbf`
- Rollback command: `git revert -m 1 b835f52b5eaf4d01652c5e40d13d8063d235bdbf`
- Ancestor proof command and result: `git merge-base --is-ancestor e45374abeb1c57aa28432b00c0c68ed45328725a main; echo $?` returned `0`.
- Pre-merge required test evidence:
  - `git diff --check` pass.
  - `env UV_CACHE_DIR=/private/tmp/codex-uv-cache uv run --extra dev python -m pytest tests` pass: 9 passed.

### pipeline_contracts Step D Canonical Campaign Draft Schema Sync

- Repo: `pipeline_contracts`
- Branch: `codex/canonical-campaign-draft-schema-sync`
- Branch tip SHA: `3f6e43a2ede15fbbb9bef854e45ee0173947e5bd`
- Pre-merge integration SHA: `b835f52b5eaf4d01652c5e40d13d8063d235bdbf`
- Merge SHA: pending
- Rollback command: `git revert -m 1 <pipeline-contracts-canonical-schema-sync-merge-sha>`
- Ancestor proof command and result: pending.
- Pre-merge required test evidence:
  - `git diff --check` pass.
  - `env UV_CACHE_DIR=/private/tmp/codex-uv-cache uv run --extra dev python -m pytest tests` pass: 9 passed.
  - `graphify update .` pass.

## Deferred Owner-Only Work

- Secret rotation and git-history purge.
- 50/100/200 scale proof and QStash outage/reconciliation-drain proof.
- Account graph certification.

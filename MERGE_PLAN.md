# Merge Plan - 2026-06-16

Integration merges performed by this resumed run are recorded below with proof.

## Integration Branch Registry

| Repo | Integration branch | Current branch at inventory | Inventory HEAD | Required pre-merge action |
| --- | --- | --- | --- | --- |
| `creator-os` | `main` | `codex/mirror-parity-gate` | merged branch tip `e73c5bc9b117fdeabba09f3aa84fa79ac7cfd2a9` | merged to `main` as `b6ca0c66ed41d1c8134645cab0de1788f2526edf`; ancestor proof exit 0 |
| `ThreadsDashboard` | `main` | `codex/autoposter-hardening` | merged branch tip `e77466edecd1891962b7ebb52047960b1c284e81` | merged to `main` as `7c3757574dd1b3d7b6d0008f1902d1e157c41577`; ancestor proof exit 0 |
| `ThreadsDashboard` | `main` | `codex/audit-port` | branch tip `22a9476890dfebfd8200c15b602c9b7d2139e1c5` | merged to `main` as `bac25a9d213f86d837e07a94559a78f935abffd9`; ancestor proof exit 0 |
| `ThreadsDashboard` | `main` | `codex/ws5-radix-boundary` | branch tip `14f913e98aae267bb1c158672250fe6bbd51e511` | merged to `main` as `22cf7b959b6058475b0f8590d9597ce81b8c2960`; ancestor proof exit 0 |
| `campaign_factory` | `main` | `codex/campaign-caption-inventory` | branch tip `99f27208c8664d488fd666e81f685ce31eebf85f` | merged to `main` as `c0912e4cf44fd40216858f75f89d8980a73c1400`; ancestor proof exit 0 |
| `reel_factory` | `main` | `codex/split-review-truth` | branch tip `4bad3acabcef1b128f02f15f16869b28e7830589` | merged to `main` as `49584b77114b6308597a6d9303bf7e8edcfd4c1d`; ancestor proof exit 0; `codex/review-truth-port@9b7f61afe76bceaa46bb3b93100730fe06620607` is red and not mergeable |
| `pipeline_contracts` | `main` | `codex/campaign-draft-contract-sync` | branch tip `e45374abeb1c57aa28432b00c0c68ed45328725a` | merged to `main` as `b835f52b5eaf4d01652c5e40d13d8063d235bdbf`; ancestor proof exit 0 |
| `pipeline_contracts` | `main` | `codex/canonical-campaign-draft-schema-sync` | branch tip `3f6e43a2ede15fbbb9bef854e45ee0173947e5bd` | merged to `main` as `94a768d10d9bb62ef3d44b4f0114a6145a5bdd71`; ancestor proof exit 0 |
| `pipeline_contracts` | `main` | `codex/ws3-trust-blocker-contract` | branch tip `5dbd2d3f094edff73086c50627254e5a81904014` | merged to `main` as `fb3226ed70a1d6d45647f0681783a14060f6aba6`; ancestor proof exit 0 |
| `campaign_factory` | `main` | `codex/ws3-qc-fail-closed` | branch tip `eb3f044d30331c88c97323d906744716693cdc94` | merged to `main` as `8bea6e64e561289af34773007aa89c6ed452cdff`; ancestor proof exit 0 |
| `campaign_factory` | `main` | `codex/ws3-contract-blocker-codes` | branch tip `e83307781d60ce82d588025dc1241ee21b36a97e` | merged to `main` as `5371570b2ce369f6c41ce474fc0e96460dffe9c8`; ancestor proof exit 0 |
| `campaign_factory` | `main` | `codex/ws6-python-maturity` | branch tip `b22e25a72e99e653339131f664ab90a2cfadb1f6` | merged to `main` as `978f886af287093c176e73b3de8393a77a5fffd1`; ancestor proof exit 0 |
| `reel_factory` | `main` | `codex/ws3-reel-backend-gates` | branch tip `f6cdf33b07071627c9846ff8d1e52e7907fc9e88` | merged to `main` as `4506e277da22d3e86c8c4eeca19334ae8130b691`; ancestor proof exit 0 |
| `reel_factory` | `main` | `codex/ws6-python-maturity` | branch tip `f6d0794aede7e936a3d2d3cef600519e476e8aa7` | merged to `main` as `a9b3029bc92ff0de7d3ec994b48ffb9ff9797136`; ancestor proof exit 0 |
| `contentforge` | `main` | `main` | `47e1293ce` | Pending only if future changes are made |
| `reference_factory` | `main` | inventory `main`; fix branch `codex/reference-test-deps` | inventory `2cf59f2a7`; fix branch `2ea2a7f` | Red pytest dependency baseline fixed and pushed; record `main` pre-merge SHA before ordered repo-maturity merge |
| `pipeline_contracts` | `main` | `codex/ws6-python-maturity` | branch tip `8520b8644c134c22127a0317d295a06a13d7f047` | merged to `main` as `1cb1106b242278c1ca9f9f56d5d2053a0ad43cc3`; ancestor proof exit 0 |
| `reference_factory` | `main` | `codex/reference-test-deps` | branch tip `a01d70b1e305e5ae777a00955153381f08079d4a` | merged to `main` as `5e8bfa73522700a54c85782643a35c75f82dd2ff`; ancestor proof exit 0 |

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
- `ThreadsDashboard`: `codex/ws5-radix-boundary@14f913e98aae267bb1c158672250fe6bbd51e511` is an ancestor of `main` after merge commit `22cf7b959b6058475b0f8590d9597ce81b8c2960`.
- `campaign_factory`: `codex/campaign-caption-inventory@99f27208c8664d488fd666e81f685ce31eebf85f` is an ancestor of `main` after merge commit `c0912e4cf44fd40216858f75f89d8980a73c1400`.
- `reel_factory`: `codex/split-review-truth@4bad3acabcef1b128f02f15f16869b28e7830589` is an ancestor of `main` after merge commit `49584b77114b6308597a6d9303bf7e8edcfd4c1d`.
- `pipeline_contracts`: `codex/campaign-draft-contract-sync@e45374abeb1c57aa28432b00c0c68ed45328725a` is an ancestor of `main` after merge commit `b835f52b5eaf4d01652c5e40d13d8063d235bdbf`.
- `pipeline_contracts`: `codex/canonical-campaign-draft-schema-sync@3f6e43a2ede15fbbb9bef854e45ee0173947e5bd` is an ancestor of `main` after merge commit `94a768d10d9bb62ef3d44b4f0114a6145a5bdd71`.

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

### ThreadsDashboard Step G Radix Boundary

- Repo: `ThreadsDashboard`
- Branch: `codex/ws5-radix-boundary`
- Branch tip SHA: `14f913e98aae267bb1c158672250fe6bbd51e511`
- Pre-merge integration SHA: `bac25a9d213f86d837e07a94559a78f935abffd9`
- Merge SHA: `22cf7b959b6058475b0f8590d9597ce81b8c2960`
- Rollback command: `git revert -m 1 22cf7b959b6058475b0f8590d9597ce81b8c2960`
- Ancestor proof command and result: `git merge-base --is-ancestor 14f913e98aae267bb1c158672250fe6bbd51e511 main; echo $?` returned `0`.
- Pre-merge required test evidence:
  - `git diff --check` pass.
  - `npm run check:ui-boundaries` pass.
  - `npm run compat:check` pass.
  - `npm run typecheck` pass.
  - `npm run test` pass: 360 files passed, 1 skipped; 4711 passed, 1 skipped, 3 todo.
  - `npm run build` pass.
  - `npm run test:e2e:critical` pass with local `npm run dev` server: 1 passed, 5 skipped.
  - `graphify update . --force` pass.
  - Direct dependency check pass: no direct `@radix-ui/*`; `radix-ui@^1.5.0`, `lucide-react@^1.17.0`, `zod@^4.4.3`; `npm ls zod --all --depth=20` showed only `zod@4.4.3`.
- TD deploy note: pushed `ThreadsDashboard/main` from `bac25a9d213f86d837e07a94559a78f935abffd9` to `22cf7b959b6058475b0f8590d9597ce81b8c2960`; no Vercel relink or deploy-config change was made.

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
- Merge SHA: `94a768d10d9bb62ef3d44b4f0114a6145a5bdd71`
- Rollback command: `git revert -m 1 94a768d10d9bb62ef3d44b4f0114a6145a5bdd71`
- Ancestor proof command and result: `git merge-base --is-ancestor 3f6e43a2ede15fbbb9bef854e45ee0173947e5bd main; echo $?` returned `0`.
- Pre-merge required test evidence:
  - `git diff --check` pass.
  - `env UV_CACHE_DIR=/private/tmp/codex-uv-cache uv run --extra dev python -m pytest tests` pass: 9 passed.
  - `graphify update .` pass.

### campaign_factory Step E QC Fail-Closed

- Repo: `campaign_factory`
- Branch: `codex/ws3-qc-fail-closed`
- Branch tip SHA: `eb3f044d30331c88c97323d906744716693cdc94`
- Pre-merge integration SHA: `c0912e4cf44fd40216858f75f89d8980a73c1400`
- Merge SHA: `8bea6e64e561289af34773007aa89c6ed452cdff`
- Rollback command: `git revert -m 1 8bea6e64e561289af34773007aa89c6ed452cdff`
- Ancestor proof command and result: `git merge-base --is-ancestor eb3f044d30331c88c97323d906744716693cdc94 main; echo $?` returned `0`.
- Pre-merge required test evidence:
  - `git diff --check` pass.
  - `env UV_CACHE_DIR=/private/tmp/codex-uv-cache uv run --extra dev python -m pytest tests/test_core.py -k "publishability or surface_handoff or visual_qc or identity"` pass: 23 passed, 341 deselected.
  - `env UV_CACHE_DIR=/private/tmp/codex-uv-cache uv run --extra dev python -m pytest tests/test_core.py::test_generate_variants_accepts_contentforge_v2_pack` pass: 1 passed.
  - `env UV_CACHE_DIR=/private/tmp/codex-uv-cache uv run --extra dev python -m pytest tests` pass: 385 passed.
  - `graphify update .` pass.

### reel_factory Step E Backend Production Gates

- Repo: `reel_factory`
- Branch: `codex/ws3-reel-backend-gates`
- Branch tip SHA: `f6cdf33b07071627c9846ff8d1e52e7907fc9e88`
- Pre-merge integration SHA: `49584b77114b6308597a6d9303bf7e8edcfd4c1d`
- Merge SHA: `4506e277da22d3e86c8c4eeca19334ae8130b691`
- Rollback command: `git revert -m 1 4506e277da22d3e86c8c4eeca19334ae8130b691`
- Ancestor proof command and result: `git merge-base --is-ancestor f6cdf33b07071627c9846ff8d1e52e7907fc9e88 main; echo $?` returned `0`.
- Pre-merge required test evidence:
  - `git diff --check` pass.
  - `env UV_CACHE_DIR=/private/tmp/codex-uv-cache uv run --extra dev python -m pytest tests/test_reel_pipeline.py tests/test_content_trust_hardening.py tests/test_grid_crop.py tests/test_advanced_roadmap.py` pass: 198 passed, 44 warnings.
  - `env UV_CACHE_DIR=/private/tmp/codex-uv-cache uv run --extra dev python -m pytest tests` pass: 313 passed, 48 warnings.
  - `graphify update .` pass.

### campaign_factory Step E Contract-Bounded Trust Blockers

- Repo: `campaign_factory`
- Branch: `codex/ws3-contract-blocker-codes`
- Branch tip SHA: `e83307781d60ce82d588025dc1241ee21b36a97e`
- Pre-merge integration SHA: `8bea6e64e561289af34773007aa89c6ed452cdff`
- Merge SHA: `5371570b2ce369f6c41ce474fc0e96460dffe9c8`
- Rollback command: `git revert -m 1 5371570b2ce369f6c41ce474fc0e96460dffe9c8`
- Ancestor proof command and result: `git merge-base --is-ancestor e83307781d60ce82d588025dc1241ee21b36a97e main; echo $?` returned `0`.
- Pre-merge required test evidence:
  - `git diff --check` pass.
  - `env UV_CACHE_DIR=/private/tmp/codex-uv-cache uv run --extra dev python -m pytest tests/test_core.py -k "publishability or surface_handoff or visual_qc or identity"` pass: 24 passed, 341 deselected.
  - `env UV_CACHE_DIR=/private/tmp/codex-uv-cache uv run --extra dev python -m pytest tests` pass: 386 passed.
  - `graphify update .` pass.

### pipeline_contracts Step E Trust Blocker Contract

- Repo: `pipeline_contracts`
- Branch: `codex/ws3-trust-blocker-contract`
- Branch tip SHA: `5dbd2d3f094edff73086c50627254e5a81904014`
- Pre-merge integration SHA: `94a768d10d9bb62ef3d44b4f0114a6145a5bdd71`
- Merge SHA: `fb3226ed70a1d6d45647f0681783a14060f6aba6`
- Rollback command: `git revert -m 1 fb3226ed70a1d6d45647f0681783a14060f6aba6`
- Ancestor proof command and result: `git merge-base --is-ancestor 5dbd2d3f094edff73086c50627254e5a81904014 main; echo $?` returned `0`.
- Pre-merge required test evidence:
  - `git diff --check` pass.
  - `env UV_CACHE_DIR=/private/tmp/codex-uv-cache uv run python -m pytest tests` pass: 10 passed.
  - `graphify update .` pass.

### campaign_factory Step F Python Maturity

- Repo: `campaign_factory`
- Branch: `codex/ws6-python-maturity`
- Branch tip SHA: `b22e25a72e99e653339131f664ab90a2cfadb1f6`
- Pre-merge integration SHA: `5371570b2ce369f6c41ce474fc0e96460dffe9c8`
- Merge SHA: `978f886af287093c176e73b3de8393a77a5fffd1`
- Rollback command: `git revert -m 1 978f886af287093c176e73b3de8393a77a5fffd1`
- Ancestor proof command and result: `git merge-base --is-ancestor b22e25a72e99e653339131f664ab90a2cfadb1f6 main; echo $?` returned `0`.
- Pre-merge required test evidence:
  - `git diff --check` pass.
  - `env UV_CACHE_DIR=/private/tmp/codex-uv-cache uv run --extra dev ruff check --select E9,F63,F7,F82 .` pass.
  - `env UV_CACHE_DIR=/private/tmp/codex-uv-cache uv run --extra dev python -m compileall campaign_factory repurposer tests` pass.
  - `env UV_CACHE_DIR=/private/tmp/codex-uv-cache uv run --extra dev python -m pytest tests` pass: 386 passed.
  - `graphify update .` pass.

### reel_factory Step F Python Maturity

- Repo: `reel_factory`
- Branch: `codex/ws6-python-maturity`
- Branch tip SHA: `f6d0794aede7e936a3d2d3cef600519e476e8aa7`
- Pre-merge integration SHA: `4506e277da22d3e86c8c4eeca19334ae8130b691`
- Merge SHA: `a9b3029bc92ff0de7d3ec994b48ffb9ff9797136`
- Rollback command: `git revert -m 1 a9b3029bc92ff0de7d3ec994b48ffb9ff9797136`
- Ancestor proof command and result: `git merge-base --is-ancestor f6d0794aede7e936a3d2d3cef600519e476e8aa7 main; echo $?` returned `0`.
- Pre-merge required test evidence:
  - `git diff --check` pass.
  - `env UV_CACHE_DIR=/private/tmp/codex-uv-cache uv run --extra dev ruff check --select E9,F63,F7,F82 .` pass.
  - `env UV_CACHE_DIR=/private/tmp/codex-uv-cache uv run --extra dev python -m compileall *.py tests` pass.
  - `env UV_CACHE_DIR=/private/tmp/codex-uv-cache uv run --extra dev python -m pytest tests` pass: 313 passed, 48 warnings.
  - `graphify update .` pass.

### pipeline_contracts Step F Python Maturity

- Repo: `pipeline_contracts`
- Branch: `codex/ws6-python-maturity`
- Branch tip SHA: `8520b8644c134c22127a0317d295a06a13d7f047`
- Pre-merge integration SHA: `fb3226ed70a1d6d45647f0681783a14060f6aba6`
- Merge SHA: `1cb1106b242278c1ca9f9f56d5d2053a0ad43cc3`
- Rollback command: `git revert -m 1 1cb1106b242278c1ca9f9f56d5d2053a0ad43cc3`
- Ancestor proof command and result: `git merge-base --is-ancestor 8520b8644c134c22127a0317d295a06a13d7f047 main; echo $?` returned `0`.
- Pre-merge required test evidence:
  - `git diff --check` pass.
  - `env UV_CACHE_DIR=/private/tmp/codex-uv-cache uv run --extra dev ruff check --select E9,F63,F7,F82 .` pass.
  - `env UV_CACHE_DIR=/private/tmp/codex-uv-cache uv run --extra dev python -m compileall pipeline_contracts tests` pass.
  - `env UV_CACHE_DIR=/private/tmp/codex-uv-cache uv run --extra dev python -m pytest tests` pass: 10 passed.
  - `graphify update .` pass.

### reference_factory Step F Dependency And Python Maturity

- Repo: `reference_factory`
- Branch: `codex/reference-test-deps`
- Branch tip SHA: `a01d70b1e305e5ae777a00955153381f08079d4a`
- Pre-merge integration SHA: `2cf59f2a7a59413202f6520cf59d29b4e443472a`
- Merge SHA: `5e8bfa73522700a54c85782643a35c75f82dd2ff`
- Rollback command: `git revert -m 1 5e8bfa73522700a54c85782643a35c75f82dd2ff`
- Ancestor proof command and result: `git merge-base --is-ancestor a01d70b1e305e5ae777a00955153381f08079d4a main; echo $?` returned `0`.
- Pre-merge required test evidence:
  - `git diff --check` pass.
  - `env UV_CACHE_DIR=/private/tmp/codex-uv-cache uv run --extra test ruff check --select E9,F63,F7,F82 .` pass.
  - `env UV_CACHE_DIR=/private/tmp/codex-uv-cache uv run --extra test python -m compileall reference_factory tests` pass.
  - `env UV_CACHE_DIR=/private/tmp/codex-uv-cache uv run --extra test python -m pytest tests` pass: 84 passed.
  - `graphify update .` pass.

## Deferred Owner-Only Work

- Secret rotation and git-history purge.
- 50/100/200 scale proof and QStash outage/reconciliation-drain proof.

## PR Merge Records

### creator-os PR #4 setup-uv v7

- Repo: `creator-os`
- PR: `#4`
- Branch: `dependabot/github_actions/astral-sh/setup-uv-7`
- Branch tip SHA: `82ce3ecc1b80347160c3945a025b88e9814640cd`
- Pre-merge integration SHA: `6f5696e25a5c06a4f58bff95150e8e77e4b1f7ae`
- Merge SHA: `be8b5ae00944e188e79ad5847a52de1d2811b078`
- Rollback command: `git revert -m 1 be8b5ae00944e188e79ad5847a52de1d2811b078`
- Ancestor proof command and result: `git merge-base --is-ancestor 82ce3ecc1b80347160c3945a025b88e9814640cd origin/main; echo $?` returned `0`.
- Pre-merge required test evidence:
  - GitHub PR checks all green: `contracts`, `Dependency review`, `architecture`, `CodeQL (javascript-typescript)`, `CodeQL (python)`, `javascript`, `Secret scan`, `visual-regression`, `Trivy filesystem scan`, `python`, `hygiene`, `sbom`, `CodeQL`, and `Trivy`.
  - PR diff is CI-only: `.github/workflows/monorepo-ci.yml` changes `astral-sh/setup-uv@v6` to `@v7`.

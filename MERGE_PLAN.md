# Merge Plan - 2026-06-16

No integration merges have been performed by this resumed run yet.

## Integration Branch Registry

| Repo | Integration branch | Current branch at inventory | Inventory HEAD | Required pre-merge action |
| --- | --- | --- | --- | --- |
| `creator-os` | `main` | `codex/mirror-parity-gate` | inventory `28846dfc8`; current `a566e25492202aa9bdf18633fe8aedca8d6a4089` | Pre-merge `main` SHA recorded below |
| `ThreadsDashboard` | `main` | `codex/autoposter-hardening` | `82f0dc839` | Reconcile branch against current `main`, rerun TD full gate including critical Playwright, then record pre-merge SHA |
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

- `creator-os`: `codex/mirror-parity-gate@a566e25492202aa9bdf18633fe8aedca8d6a4089` is 3 commits ahead of `main`; merge pending.
- `ThreadsDashboard`: `codex/autoposter-hardening@82f0dc839` is 10 behind and 4 ahead of `main`; merge pending after reconciliation and fresh gates.
- `campaign_factory`: `codex/campaign-caption-inventory@99f27208c` is 1 behind and 1 ahead of `main`; merge pending.
- `reel_factory`: `codex/split-review-truth@4bad3acab` is 2 ahead of `main`; merge pending.
- `pipeline_contracts`: `codex/campaign-draft-contract-sync@e45374abe` is 1 behind and 1 ahead of `main`; merge pending.

## Current Red Gates Blocking Merges

- None currently after `reference_factory/codex/reference-test-deps@2ea2a7f` fixed the `httpx2` test extra and reran 84 passing tests. Merges still require fresh pre-merge gates.

## Planned Merge Records

### creator-os WS1 Mirror Parity

- Repo: `creator-os`
- Branch: `codex/mirror-parity-gate`
- Branch tip SHA before pre-merge record: `a566e25492202aa9bdf18633fe8aedca8d6a4089`
- Pre-merge integration SHA: `c1b70250c26845a8c5629dee7b87d5e3b6d8de28`
- Planned rollback command after merge SHA is known: `git revert -m 1 <creator-os-ws1-merge-sha>`
- Pre-merge required test evidence:
  - `pnpm check:mirror-parity` pass at `a566e25492202aa9bdf18633fe8aedca8d6a4089`.
  - `pnpm check:contracts` pass.
  - `pnpm check:artifacts` pass.
  - `env UV_CACHE_DIR=/private/tmp/codex-uv-cache pnpm check:arch` pass.
  - `pnpm --filter juno33 typecheck` pass.
  - `pnpm --filter juno33 test` pass: 359 files passed, 1 skipped; 4701 passed, 1 skipped, 3 todo.
  - `env UV_CACHE_DIR=/private/tmp/codex-uv-cache uv run pytest packages/pipeline_contracts/tests python_packages/campaign_factory/tests python_packages/reel_factory/tests python_packages/reference_factory/tests tests/integration` pass: 795 passed, 48 warnings.

## Deferred Owner-Only Work

- Secret rotation and git-history purge.
- 50/100/200 scale proof and QStash outage/reconciliation-drain proof.
- Account graph certification.

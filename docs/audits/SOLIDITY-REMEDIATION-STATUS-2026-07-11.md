# Creator OS Solidity Remediation Status

**Updated:** 2026-07-11  
**Creator OS baseline:** `aa9eaa58c0f3bb1b1de4ddf13d29cb12c1033604`  
**ThreadsDashboard baseline:** `0b5f09126fa4127afc7565410e08d57de49fb062`

This document separates implementation, repository rollout, deployment, runtime,
and live-payload proof. A checked implementation item is not automatically
merged or deployed.

## Completed locally

### Creator OS

- [x] Correct active Reel producers to emit
  `reel_factory.generated_asset_lineage.v2`.
- [x] Add regression coverage that forbids the incorrect Campaign Factory
  lineage authority in active Reel source.
- [x] Correct the documented canonical schema directory to
  `packages/pipeline_contracts/pipeline_contracts/schemas`.
- [x] Correct contract generator, import-shim, TypeScript output, pre-commit,
  system-map, package README, and repo-map wording.
- [x] Remove three CI commands targeting the deleted Command Center package.
- [x] Add a CI guard proving ContentForge remains tested and Command Center is
  absent.
- [x] Commit the slice locally as `710b54a0` on
  `codex/solidity-integrity-fixes`.

Verification:

- [x] `make verify`
- [x] Pipeline Contracts Python: 36 passed
- [x] Pipeline Contracts TypeScript: 21 passed
- [x] Creator OS Core: 5 passed
- [x] ContentForge: 128 passed
- [x] Campaign Factory: 637 passed
- [x] Reference Factory: 149 passed
- [x] Reel Factory: 606 passed
- [x] Integration: 30 passed
- [x] Static, formatting, contract, architecture, and artifact gates passed

### ThreadsDashboard

- [x] Inspect returned Supabase errors for Threads and Instagram
  `post_metric_history` inserts.
- [x] Inspect returned Supabase errors for Threads and Instagram history
  retention deletes.
- [x] Add regression coverage for all four returned-error checks.
- [x] Include `scripts/vercel-ignore-build.mjs` in Vercel deployment packaging.
- [x] Add a CI-cost regression test for the Vercel ignore script.
- [x] Commit the slice locally as `a6a08fe66` on
  `codex/solidity-integrity-fixes`.

Verification:

- [x] Vitest: 5,270 passed, 23 skipped, 3 todo
- [x] TypeScript typecheck
- [x] Biome lint
- [x] Compatibility and boundary checks
- [x] Pipeline contract parity
- [x] Bundle budgets
- [x] Production build

## Rollout status for completed code

- [ ] Reconcile the independent Claude audit with the two local commits.
- [ ] Push the Creator OS branch and open a focused PR.
- [ ] Push the ThreadsDashboard branch and open a focused PR.
- [ ] Obtain current-head CI evidence for both PRs.
- [ ] Merge only after the independent audit does not invalidate the fixes.
- [ ] Deploy the exact merged ThreadsDashboard SHA to production.
- [ ] Verify production logs and metric-history failure reporting after deploy.

No code in this status section has been pushed, merged, or deployed yet.

## Remaining P0 work

### Production database authority

- [ ] Recover the exact SQL for these production-only Supabase migrations:
  - `20260710202159`
  - `20260710202201`
  - `20260710210155`
  - `20260710210651`
  - `20260710211000`
  - `20260710211408`
  - `20260710224309`
  - `20260710233000`
  - `20260710234500`
  - `20260711014555`
- [ ] Review recovered SQL for grants, RLS, views, storage policies, triggers,
  and `SECURITY DEFINER` functions.
- [ ] Replay the complete migration chain on a clean database.
- [ ] Require exact local/remote migration parity.
- [ ] Compare critical production schema and policy checksums with the replayed
  database.

Do not apply additional production migrations until source control is again
authoritative.

### CI and production deployment governance

- [ ] Restore ThreadsDashboard GitHub Actions execution; current jobs fail
  before running steps or producing logs.
- [ ] Require quality and secret-scan evidence before production deployment.
- [ ] Prove a failing check cannot reach Vercel production.
- [ ] Prove the exact green commit is the commit promoted to production.
- [ ] Add enforceable branch rules when the repository plan supports them.

### Closed-loop live certification

- [ ] Manually select native Instagram audio for one approved cohort draft.
- [ ] Publish at the approved operator window.
- [ ] Reconcile the external Instagram media ID without duplicates.
- [ ] Prove one exact 1-hour metric snapshot.
- [ ] Prove one exact 24-hour metric snapshot.
- [ ] Prove idempotent Campaign, Reel, and Reference learning fanout.
- [ ] Prove correction or retraction updates downstream learning deterministically.
- [ ] Complete 50 eligible posts with both required metric windows before any
  autonomy claim.

Current cohort truth: 50 assignments, 2 approved drafts, 0 published cohort
posts, and 0 completed 1-hour/24-hour pairs.

## Remaining P1 work

### Runtime integrity and least privilege

- [ ] Emit a launchd startup manifest containing code SHA, allowed dirty paths,
  database path/schema, dependency versions, and configuration hashes.
- [ ] Stop the runtime checkout from depending silently on a database in another
  checkout.
- [ ] Move generated evidence and models outside the code checkout or explicitly
  allowlist them in the runtime manifest.
- [ ] Load credentials per job instead of sourcing Campaign Factory ingest
  secrets for every wrapped launchd job.
- [ ] Prove backup and ops-digest jobs cannot read ingest or Supabase
  service-role credentials.
- [ ] Add non-overlap, sleep/wake, stale-environment, timeout, and partial-phase
  recovery tests for the hourly job.

### Security and failure evidence

- [ ] Produce one consolidated live HMAC evidence bundle proving:
  - signed success;
  - fresh-nonce idempotent retry without duplication;
  - exact-nonce replay rejection;
  - tampered-body rejection;
  - stale-timestamp rejection;
  - zero schedule, queue, or publish side effects.
- [ ] Replace raw shell interpolation in Discord alert JSON with a real JSON
  encoder.
- [ ] Record webhook delivery failures instead of discarding them.
- [ ] Test alert quotes, newlines, backslashes, redaction, and failed delivery.

### Learning and provider integrity

- [ ] Add a canonical Reference Factory campaign-reference-bank contract.
- [ ] Validate Reference and audio payloads during normal imports, not only
  smoke paths.
- [ ] Surface reference-bank source run ID and import age in readiness and ops
  digest.
- [ ] Attribute all paid provider reservations to cohort and assignment IDs in
  provider-native credit units.
- [ ] Prove concurrency and ledger failures produce zero unauthorized provider
  calls.

## Remaining P2 hardening

- [ ] Monitor Supabase offsite backup, repository-check, and restore-drill
  freshness in ops digest.
- [ ] Add a production Supabase recovery/reconciliation drill in addition to the
  local encrypted SQLite restore drill.
- [ ] Update `PIPELINE_STATE.md` after the rollout is settled.
- [ ] Regenerate Graphify with compatible tool/package versions and exclude
  deleted build artifacts.
- [ ] Pin the supported local Node runtime used by `make verify`.
- [ ] Expand mypy coverage beyond Pipeline Contracts in staged, package-sized
  increments.
- [ ] Review ContentForge's reported unused file, exports, duplicate export, and
  external binary declarations before deleting anything.
- [ ] Make Creator OS Doctor label fixture proof separately from live runtime
  proof and fail documentation checks on nonexistent canonical paths.

## Safety holds

- Autoposter remains disabled.
- Automatic Trial Reel graduation remains disabled.
- Creator OS remains draft-only; ThreadsDashboard owns scheduling and publishing.
- Native Instagram audio remains a manual operator step for the current account.
- No production migration, deployment, paid generation, schedule, or publish
  action is authorized by this document.

## Definition of done

The solidity remediation is complete only when:

1. Repository migrations reproduce production exactly.
2. Failed CI cannot deploy to production.
3. The completed code fixes are merged, deployed, and runtime-verified.
4. One real post completes publish, 1-hour metrics, 24-hour metrics, and
   idempotent learning fanout.
5. The full 50-post eligible cohort supplies the evidence required for any
   autonomy decision.


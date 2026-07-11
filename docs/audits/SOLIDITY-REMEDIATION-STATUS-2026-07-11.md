# Creator OS Solidity Remediation Status

**Updated:** 2026-07-11  
**Creator OS baseline:** `aa9eaa58c0f3bb1b1de4ddf13d29cb12c1033604`  
**ThreadsDashboard baseline:** `0b5f09126fa4127afc7565410e08d57de49fb062`

This document separates implementation, repository rollout, deployment, runtime,
and live-payload proof. A checked implementation item is not automatically
merged or deployed.

The six-lane consolidated read-only audit has now been reconciled. Its source
baselines match the baselines above. ThreadsDashboard production provenance is
still unknown because the active Vercel deployment has no Git source metadata;
behavioral similarity to a SHA is not provenance proof.

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
- [x] Add deterministic cohort metric writeback to the hourly performance sync.
- [x] Derive 1-hour, 24-hour, and trial 72-hour state only from eligible metric
  history snapshots.
- [x] Compute `reward_24h` from the actual selected 24-hour snapshot.
- [x] Revert completion and reward state when metric evidence is retracted.
- [x] Fail closed without `LEARNING_LOOP_CUTOVER`.
- [x] Commit the metric-writeback slice locally as `eff6a67`.
- [x] Replace FFmpeg's looping-audio `-shortest` termination with the exact
  probed video duration, eliminating the CI-only 180-second mux hang.

Verification:

- [x] `make verify`
- [x] Pipeline Contracts Python: 36 passed
- [x] Pipeline Contracts TypeScript: 21 passed
- [x] Creator OS Core: 5 passed
- [x] ContentForge: 128 passed
- [x] Campaign Factory: 639 passed
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
- [x] Permit a newly fenced retry of failed Campaign Factory ingest claims.
- [x] Reconcile durable Instagram publish evidence before declaring a live post
  failed.
- [x] Enforce the operator kill switch on new and container-retry Instagram cron
  publishing.
- [x] Fail loudly if a pending Instagram container cannot be persisted.
- [x] Schedule the missing 72-hour account and direct Instagram metric jobs.
- [x] Commit the ingest/publish hardening slice locally as `ad10d0102`.

Verification:

- [x] Vitest: 5,276 passed, 23 skipped, 3 todo
- [x] TypeScript typecheck
- [x] Biome lint
- [x] Compatibility and boundary checks
- [x] Pipeline contract parity
- [x] Bundle budgets
- [x] Production build

### Local runtime operations

- [x] Wrap offsite backup, repository-check, and restore-drill launchd agents in
  `~/.creator-os/run-job.sh`.
- [x] Restrict Campaign Factory ingest credentials to the performance-sync job.
- [x] Encode Discord alert JSON with a JSON serializer and record delivery
  failures.
- [x] Pin the offsite scripts to `/opt/homebrew/bin/supabase` version `2.90.0`.
- [x] Reload all three launchd agents and verify their registered arguments.
- [x] Run a real read-only offsite repository check through the wrapper; Restic
  reported no errors at `2026-07-11T08:38:12Z`.

## Rollout status for completed code

- [x] Reconcile the independent consolidated audit with the two local branches.
- [x] Push the Creator OS branch and open draft PR `#400`.
- [x] Push the ThreadsDashboard branch and open draft PR `#297`.
- [ ] Obtain current-head CI evidence for both PRs.
- [ ] Merge only after the independent audit does not invalidate the fixes.
- [ ] Deploy the exact merged ThreadsDashboard SHA to production.
- [ ] Verify production logs and metric-history failure reporting after deploy.

No code in this status section has been pushed, merged, or deployed yet.

## Remaining P0 work

### Production database authority

The earlier ten-migration characterization was disproved by the consolidated
audit. The confirmed divergence is one functionally equivalent ledger mismatch:
source migration `20260711014400` is not recorded as applied, while production
records remote migration `20260711014555`; their trigger statements are
byte-identical.

- [ ] Preserve source migration `20260711014400`; do not merge the branch that
  deletes it.
- [ ] Repair the production migration ledger for `20260711014400` only after an
  exact dry-run review of the linked project.
- [ ] Add and apply a reviewed migration revoking `authenticated` execution on
  the five audited workspace-predicate `SECURITY DEFINER` functions.
- [ ] Replay the complete migration chain on a clean database.
- [ ] Require exact local/remote migration parity.
- [ ] Compare critical production schema and policy checksums with the replayed
  database.

Do not apply additional production migrations until source control is again
authoritative.

### Production deployment provenance and governance

- [ ] Identify the exact source SHA of the active ThreadsDashboard deployment;
  current deployment `dpl_61qLci4ZVs9PX4kdRH5jG3CfXtxH` is ready but its
  Vercel metadata contains no Git source.
- [ ] Prevent hand-CLI production deployment without recorded source SHA.
- [ ] Restore GitHub Actions execution; current jobs fail before checkout due
  billing/account state. PR `#297` reproduced this with zero job logs for both
  quality and secret-scan checks.
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

Current cohort truth at audit time: 50 assignments, 2 ingested drafts, 48
planned assignments, 0 published cohort posts, and 0 completed 1-hour/24-hour
pairs. The missing writeback stage is now implemented locally, but no metrics
were fabricated and readiness remains `0/50` until real posts mature.

## Remaining P1 work

### Runtime integrity and least privilege

- [ ] Emit a launchd startup manifest containing code SHA, allowed dirty paths,
  database path/schema, dependency versions, and configuration hashes.
- [ ] Stop the runtime checkout from depending silently on a database in another
  checkout.
- [ ] Move generated evidence and models outside the code checkout or explicitly
  allowlist them in the runtime manifest.
- [x] Load Campaign Factory ingest credentials only for performance sync.
- [x] Prove the offsite jobs do not receive the Campaign Factory ingest secret.
- [ ] Split remaining job credentials so backup and ops-digest processes receive
  only their exact required secrets.
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
- [x] Replace raw shell interpolation in Discord alert JSON with a real JSON
  encoder.
- [x] Record webhook delivery failures instead of discarding them.
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

- [ ] Resolve shared-fate offsite storage: the current backup bucket and
  production database live in the same Supabase project.
- [ ] Add a periodic logical production Postgres dump retained beyond the
  platform's seven-day PITR window.
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
- [ ] Make ContentForge unsafe-audit approval blocking by default.
- [ ] Remove or strictly allowlist the `legacy_compat` lineage-validation escape.
- [ ] Add retry/backoff and alerting for terminal `failed_capped` learning fanout.
- [ ] Remove the legacy raw service-role write path after required backfills are
  migrated to an audited tool.

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
4. One real post completes publish, 1-hour metrics, 24-hour metrics, cohort
   writeback, and idempotent learning fanout.
5. The full 50-post eligible cohort supplies the evidence required for any
   autonomy decision.

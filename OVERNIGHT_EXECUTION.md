# Overnight Execution — Creator OS Remediation

**For:** Codex (autonomous overnight run)
**Authority doc:** `REMEDIATION_MASTER_PLAN.md` (workstreams, file:line, acceptance, resolved owner decisions §11). This file is the **ordered, safety-railed runbook** to execute it.
**Goal:** get everything that is code-doable to green, committed, and merge-ready by morning — without risking the live product unattended.

---

## HARD SAFETY RAILS (violating these is failure, not progress)

1. **`ThreadsDashboard` MAY be merged to `main`** (owner approved). It auto-deploys to live `juno33.com`, so for EACH TD merge: (a) the full `pnpm --filter juno33 typecheck` + `test` + `npm run compat:check` + Playwright `critical` suite must be green first; (b) record the pre-merge SHA and the one-line revert command in `MERGE_PLAN.md` as the rollback; (c) merge one workstream at a time, not a giant combined merge, so a bad deploy is easy to bisect/revert. If any suite is red, do NOT merge that piece — leave it on its branch and note it.
2. **DO NOT do secret work.** No key rotation, no git-history purge, no `.env` changes. Owner console action only. You may prepare a `git-filter-repo` script as a file, not run it.
3. **DO NOT change behavior** of scheduling, publishing, account-health, QStash, or metrics sync. Only the named gate fixes.
4. **DO NOT commit runtime data** (media, models, DBs, uploads, node_modules, build output, `__pycache__`, `*.egg-info`). Honor the gitignore policy.
5. **Verify, don't claim.** Every "done" cites a passing command + grep evidence. Report true git state (branch vs main, committed vs dirty). Never call a thing done if only a monorepo copy has it and the live split repo doesn't.
6. **Mergeable overnight, ONLY after that repo's full test suite is green:** all repos including `ThreadsDashboard` (per rail #1 — green + rollback recorded + one workstream per merge). Non-deploying repos (`creator-os`, `campaign_factory`, `reel_factory`, `reference_factory`, `contentforge`) merge under the same green-tests gate. If a suite is red, leave on a branch and note it — never merge red.
7. Per repo before any commit: tests pass, `git diff --check` clean, `graphify update .` after touching it. Commit in small single-purpose slices. Report SHAs.

---

## Execution order

### Step A — Finish WS1 (parity gate) in `creator-os`  [highest priority]

Branch `codex/mirror-parity-gate` already exists (commit `28846df`) with the sync + parity tooling. The gate currently reports ~2,100 files of historical drift. Reconcile the baseline and make the gate blocking.

1. `node scripts/sync/mirror-sync.mjs` — regenerate all mirrors from pinned source SHAs.
2. Review the resulting diff per mirror. The `apps/dashboard` "changed" set will include legitimate **monorepo-workspace-only** files (e.g. workspace `package.json` fields, tsconfig path aliases, turbo/pnpm config, any monorepo-specific CI). For each such file that *should* differ from standalone TD, add its path to that mirror's `exclude` in `mirror-sources.json` (do NOT overwrite intentional monorepo config). Re-run sync. Repeat until the only remaining diffs are genuine stale copies + junk.
3. Confirm junk is gone (no `__pycache__/`, `*.egg-info/`, build output in any mirror). Extend `excludeDefault` if any slipped through (add `*.egg-info/`, `*.pyc`).
4. `pnpm check:mirror-parity` (blocking) must now exit 0.
5. Flip CI: in `.github/workflows/monorepo-ci.yml` add `pnpm check:mirror-parity` as a required step (replace any report-only reference). For CI auth to the sibling repos, implement the `MIRROR_SYNC_TOKEN` clone-at-SHA path documented in `scripts/sync/README.md` (clone each `sourceRepoPath` at its pinned SHA into the workspace before the check).
6. Commit; merge `codex/mirror-parity-gate` → `creator-os` `main` (creator-os is not deployed). Report SHA.
   **Acceptance:** hand-edit a mirror file → `pnpm check:mirror-parity` FAILS naming it; after `sync:mirrors` it PASSES; `pipeline_contracts` untouched; CI step is required.

### Step B — Unblock the live TD worktree (do NOT merge TD main)

The live `ThreadsDashboard` repo has a dirty `codex/autoposter-hardening` worktree (uncommitted autoposter/UI/migration files) blocking everything TD.

1. Inspect the dirty + untracked files. Commit the coherent autoposter/UI work to `codex/autoposter-hardening` in logical slices (do not lose it). If anything is clearly throwaway, stash it with a labeled stash, don't delete.
2. Reconcile stray branches `codex/autoposter-content-performance-fix` and `codex/autoposter-content-quality-hotfix` against `codex/autoposter-hardening` — fold in or document as superseded.
3. Run `pnpm --filter juno33 typecheck` + `test` + `npm run compat:check` + Playwright `critical` on the branch; record counts.
4. Merge `codex/autoposter-hardening` → TD `main` per rail #1 (green + rollback SHA in `MERGE_PLAN.md`, this merge alone). This takes the autoposter hardening LIVE. Report merge SHA + rollback command.

### Step C — Port `draftIngest.ts` to live TD

On a TD branch off `main` (`codex/audit-port`): add `draftIngest.ts` mirroring `creator-os` `main` — deterministic (non-regex) auth parse, explicit-IG-caption enforcement, surface + visual-QC + identity blocks. Tests + typecheck + compat + critical e2e green, then merge to TD `main` per rail #1 (separate merge, rollback recorded). (Reference impl: `apps/dashboard/api/_lib/handlers/campaign-factory/draftIngest.ts`.)

### Step D — Merge WS2 ports in the non-deploying split repos

- `campaign_factory`: merge `f2e43b8` (caption removal + inventory reservation + ingest routing) → `main` after `uv run pytest campaign_factory/tests` is green.
- `reel_factory`: merge `a87f8ea` (`review_truth.py`) → `main` after `uv run pytest reel_factory/tests` is green.
- Then in `creator-os`: `node scripts/sync/mirror-sync.mjs --update --only python_packages/campaign_factory` and same for `reel_factory`; commit the regenerated mirrors + bumped SHAs; `pnpm check:mirror-parity` stays green.

### Step E — WS3 remaining backend (split repos; merge if non-deploying + green)

Per `REMEDIATION_MASTER_PLAN.md` §6, in the relevant split repos:
1. **#5 ingest routing live** — CF production draft writes go through the validated ingest path; raw service-role write only behind the explicit local-test flag.
2. **Metadata normalization mandatory** — wire `media_metadata.py` as a required post-render step in `reel_pipeline.py`; test asserts encoder/handler tags stripped on every mp4.
3. **QC fail-closed everywhere** — missing/unavailable visual QC OR identity hard-blocks all readiness/handoff paths (`campaign_factory core.py:~21280-21282`), not just ingest.
4. **Identity `.venv` pin** — production render aborts loudly if the InsightFace provider is unavailable (system python reports `unavailable`).
5. **#10 deprecation** — guard `six_pack`/`grid-crop`/`grok-4` (`generate_assets.py` 5 hits, `reel_gui.py` 8 hits) behind a raise-on-call flag, or delete.
Merge each to the split repo's `main` after its suite is green; then re-sync the affected mirror in creator-os.

### Step F — WS6 repo maturity (mergeable)

1. Wire `gitleaks` into CI (`creator-os/.gitleaks.toml` exists, unused) with a `juno_ak_` rule; required gate.
2. Delete PROOF.json theater (`CAPTION_OUTCOME_TRACKING_V1_PROOF.json`, `CLOSED_LOOP_PROOF.json`, +2) or convert to real tests.
3. Add lint + typecheck to the pytest-only split Python repos.
4. Untrack `ThreadsDashboard/output/` screenshots, merge per rail #1. Do NOT rewrite git history (coordinate with the owner secret purge later).

### Step G — Frontend (WS5)

Branch `codex/frontend-cleanup` (= `codex/frontend-cleanup-rebased`, same tip `2e92f60`) holds the current work. Verified state (do NOT re-claim these as new):
- ✅ **Radix standardized** — 0 granular `@radix-ui/*`, 36 unified `radix-ui`. Real. Merge it.
- ❌ **"Decomposition" is FAKE — it is a file MOVE, not a decomposition.** `pages/Composer.tsx` was emptied and its 5,901 lines moved verbatim into `components/composer/ComposerScreen.tsx` (still one 5,901-line file); Autopilot same → `AutopilotScreen.tsx` (4,374 lines). This does NOT meet the goal. **Hard acceptance: no single component file may exceed 800 LOC.** A rename/move FAILS this check. Real fix: split `ComposerScreen.tsx` / `AutopilotScreen.tsx` into focused panel components + colocated hooks, each <800 LOC, behavior identical, tests + critical e2e green. **This is judgment-heavy — if you cannot split it safely without behavior risk, STOP, leave it on the branch, and flag in `OVERNIGHT_STATUS.md` as "needs human decomposition" rather than shipping a fake move.**
- 🟡 **ui/shadcn boundary guard** — `apps/dashboard/scripts/check-ui-boundaries.mjs` exists but is NOT wired. Wire it into `package.json` + compat:check so it actually runs and fails on raw `shadcn/` imports in routes.
- ❌ **P2, do these:** Zod single-major converge; lucide-react provenance check (confirm `^1.17.0` is the genuine package); registry-add review note documented.

**Merge policy for WS5:** merge the genuinely-complete pieces to TD `main` per rail #1 (Radix, boundary-guard-wired, zod, lucide) only after green tests + critical e2e + rollback recorded. Do NOT merge a decomposition that is just a move — it must pass the <800-LOC-per-component acceptance or stay on the branch.

---

## Deliverables by morning

1. **`MERGE_PLAN.md`** at repo root: a RECORD of every merge performed — per merge: repo, branch, merge SHA, pre-merge SHA, the one-line revert/rollback command, and (for TD) the deploy it triggered. List anything left UNmerged (red suite) separately with the failure. This is the owner's rollback map if any live deploy misbehaves.
2. **`OVERNIGHT_STATUS.md`**: per workstream — done/branch/blocked, SHAs, exact test commands + counts, any red suite left on a branch with the failure, anything you could not safely match between split and monorepo.
3. Owner decisions are already resolved in `REMEDIATION_MASTER_PLAN.md` §11 (inventory TTL 7d; proven-account bar = Codex default; Higgsfield budget = cap at current plan balance, hard-stop near zero; reel/campaign/contentforge stay split for now, TD permanently standalone). Do not re-ask; if a NEW decision surfaces, note it in OVERNIGHT_STATUS.md and proceed on the safest reversible default.

## Do NOT attempt (owner only)
- Secret rotation / OAuth re-encryption / git-history purge — provider consoles + coordinated rewrite.
- Scale proof (50/100/200 load, QStash-outage/reconciliation-drain) — operational.
- Any merge whose test suite is red — leave on branch, report the failure.

## Report format
End with: branches touched + SHAs; what merged vs awaiting-owner; total tests passed per repo; the `MERGE_PLAN.md` and `OVERNIGHT_STATUS.md` paths; any blocker with the exact error. No "done" without the receipt.

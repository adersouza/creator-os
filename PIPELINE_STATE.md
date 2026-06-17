# Pipeline State

**Last updated:** 2026-06-16. This is the single source of truth for the current state of the Creator OS pipeline. It supersedes the old one-shot planning/runbook/audit docs (removed). Operational details live in `ARCHITECTURE.md`, `AGENTS.md`, `scripts/sync/README.md`, and `docs/`.

## Architecture (two active product repos)

```
creator-os (this monorepo) — canonical runtime for the whole pipeline
├── apps/contentforge                  canonical (was a standalone repo)
├── python_packages/reel_factory       canonical
├── python_packages/campaign_factory   canonical
├── python_packages/reference_factory  canonical
├── packages/pipeline_contracts        shared contracts (canonical here; also its own repo)
├── apps/dashboard                     READ-ONLY MIRROR of ThreadsDashboard (tests only; never deployed, never hand-edited)
├── tests/integration                  cross-tool integration
└── scripts/sync/                      mirror sync + parity gate (drift protection)

ThreadsDashboard (separate repo) ──deploys──▶ juno33.com   (the standalone product; permanently NOT in the monorepo)
pipeline_contracts (separate repo)                          (contracts package)
reel_factory / campaign_factory / contentforge / reference_factory  ──▶ ARCHIVED/frozen on GitHub (soak backup)
```

## What is done

- **Monorepo↔split drift: solved structurally.** One canonical copy per tool. The `mirror-parity` gate is CI-blocking and enforced by branch protection — a hand-edit to the only remaining mirror (`apps/dashboard`) fails CI. Fixes flow source→mirror via `node scripts/sync/mirror-sync.mjs`.
- **Consolidation (Steps 1–5) complete.** The four tools are canonical in creator-os and runnable from root (`scripts/run/*` wrappers; combined `uv run pytest` green). Their standalone repos are archived (read-only, reversible). Source-of-truth flipped: only `apps/dashboard` remains a mirror.
- **Backend audit work merged + live (independently verified 2026-06-16):** autoposter safety gates, identity/ArcFace verification + `.venv` pin (aborts loudly if provider down), inventory reservation, ingest routing (raw service-role writes gated behind a prod-disabled flag; default routes to validated Dashboard ingest), QC fail-closed (visual QC + identity block readiness; `opencv_unavailable` → not "passed"), metadata normalization (required post-render step in `reel_pipeline.py`, tested). NOTE: three backend items previously reported "done" were verified NOT done — see Open work #2–#4.
- **ThreadsDashboard/juno33:** live, green on its own CI. Autoposter hardening + draft-ingest + Step G (radix unification, ui/shadcn boundary guard) shipped.
- **Governance:** branch protection on creator-os main (9 required checks, strict, enforce-admins, PR-required), gitleaks, parity gate, contracts/architecture checks.

## Current health

- creator-os `main` green except for a **flaky test** (see open work #1). TD/juno33 healthy.
- Branch protection is ON — all changes to creator-os main go via PR with green checks. No direct pushes, no `--no-verify`, no admin bypass.

## Open work

1. **[flaky gate — fix soon] Make the `campaignSchedule` tests deterministic.** `tests/unit/campaignSchedule.test.ts` (in ThreadsDashboard source; mirrored at `apps/dashboard/`) is **intermittently flaky** on the `javascript` required check: 3 tests failed twice in a row in one time window (briefly blocking merges), then passed on later runs — main is currently green. Affected: "reports campaign schedule rows with qstash state and duplicate counts", "surfaces duplicate visual risk in manager reports", "buckets accounts by safe, scheduled, and blocked states without overlap". Root cause: the file mixes `Date.now()`-relative fixtures with HARDCODED dates (`2026-06-07`/`2026-07-07` windows, `Date.UTC(2026,5,...)`) and uses NO `vi.setSystemTime`, so schedule-bucketing flips depending on the wall-clock at run time. It's not permanently red, but it will keep randomly reddening the gate. Fix in **ThreadsDashboard source**: freeze the clock with `vi.setSystemTime(<fixed reference consistent with the fixtures>)` in a `beforeEach` (and/or convert the hardcoded dates to `Date.now()`-relative) so the 3 tests assert stable, correct behavior; run the full TD suite several times (at different times) to prove determinism; merge to TD main; then `node scripts/sync/mirror-sync.mjs --update --only apps/dashboard` and commit the re-pin. Do not delete/skip the tests.
2. **[live safety — verified OPEN] Cross-account media reuse bypassed on manual flows.** The Threads autoposter enforces the cross-account media-fingerprint reuse gate (`apps/dashboard/api/_lib/handlers/auto-post/scheduleAndInsert.ts:1269-1290` — `findRecentMediaFingerprintAcrossAccounts`), but **manual/non-autoposter publish flows bypass it entirely**: `apps/dashboard/api/_lib/handlers/posts/publish.ts` (manual publish, Threads+IG), `handleSchedule`, and the QStash scheduled-publish orchestrator (`publishPost.ts`) have NO fingerprint/cross-account-reuse check — they call `runPublishPreflight()` only. Fix: route manual publish/schedule/repost paths through the same posting-ledger + media-fingerprint reuse gate the autoposter uses (or a shared preflight step), so byte-identical cross-account media reuse is blocked on every publish path, not just autoposter.
3. **[live safety — verified PARTIAL] Discoverability check is REELS-only at publish.** `apps/dashboard/api/_lib/publishPreflight.ts:455` applies the off-platform discoverability check only when `igMediaType === "REELS"`; feed (single/carousel) and Story posts skip it. (Campaign Factory `core.py:21797` already applies it to all surfaces — the gap is the live Dashboard publish path.) Fix: extend the publishPreflight discoverability check to all IG surfaces, not just REELS.
4. **[verified OPEN] Deprecated grok/grid/six_pack still reachable in prod.** The kill-switch exists but is **opt-in and OFF by default** — `REEL_FACTORY_RAISE_ON_DEPRECATED_GENERATORS=1` is set only in tests. So in production: `reel_gui.py:2042` defaults `model="grok-4.3"`, `/api/grid-crop/*` endpoints (`reel_gui.py:1337-1431`) are unconditionally live (no guard call at all), `detect_grid_status` (`generate_assets.py:486`) is unguarded, and `_six_pack_prompts` runs under `--image-mode six-pack`. Fix: make the guard raise-on-call by DEFAULT (invert the flag) or delete the deprecated paths; add a guard to the `/api/grid-crop` endpoints which currently have none.
5. **Dependabot:** 4 safe GitHub-Actions bumps are auto-merging (CI-gated). 4 majors parked as backlog, each needs a deliberate tested migration, NOT a blind merge: creator-os #12 Tailwind v3→v4, #13 ESLint 9→10, #18 (28-dep group); ThreadsDashboard #119 (29-dep group on the live product).
6. **Frontend decomposition debt:** `Composer.tsx` (~5905 LOC) + `Autopilot.tsx` (~4390 LOC) still monolithic. Tracked in **ThreadsDashboard issue #120** with the seam map. Prerequisite before any cut: add e2e for the deep-link (`?draft=`/`?accountId=`/`?date=`) and `location.state` handoff paths (current `composer-critical.spec.ts` covers only publish). Do NOT merge a rename as a decomposition.
7. **Soak + optional delete:** 7-day soak started 2026-06-16 (earliest delete ~2026-06-23). Run the pipeline from creator-os; archived repos are the rollback (`gh repo unarchive` + anchors in `CONSOLIDATION_STATUS.md`). After a clean soak, deleting the four archived repos is owner-gated and optional (archived is harmless).

## Owner-only (out of scope for automated agents)

- Secret rotation / OAuth re-encryption / git-history purge (P0) — provider consoles. See `docs/security/`.
- Scale proof (50/100/200 load, QStash-outage/reconciliation-drain).
- Account-graph certification.

## Rollback references (keep until soak ends)

- `MERGE_PLAN.md` — every live merge with pre-merge SHA + one-line revert (juno33 deploy rollback map).
- `CONSOLIDATION_STATUS.md` — per archived repo: ARCHIVED.md commit, pre-archive SHA, `gh repo unarchive` + revert commands, soak start.

## How to work here

- Fix a tool: edit it in creator-os (it's canonical now), open a PR, green checks, merge.
- Edit the dashboard mirror: NEVER directly. Fix in ThreadsDashboard source, then `node scripts/sync/mirror-sync.mjs --update --only apps/dashboard` and commit the re-pin.
- See `AGENTS.md` for agent conventions, `ARCHITECTURE.md` for system design, `scripts/sync/README.md` for the mirror model.

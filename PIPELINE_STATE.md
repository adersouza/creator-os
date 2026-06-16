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
- **Backend audit work merged + live:** autoposter safety gates, identity/ArcFace verification, inventory reservation, ingest routing, QC fail-closed, metadata normalization, deprecation guards.
- **ThreadsDashboard/juno33:** live, green on its own CI. Autoposter hardening + draft-ingest + Step G (radix unification, ui/shadcn boundary guard) shipped.
- **Governance:** branch protection on creator-os main (9 required checks, strict, enforce-admins, PR-required), gitleaks, parity gate, contracts/architecture checks.

## Current health

- creator-os `main` green except for a **flaky test** (see open work #1). TD/juno33 healthy.
- Branch protection is ON — all changes to creator-os main go via PR with green checks. No direct pushes, no `--no-verify`, no admin bypass.

## Open work

1. **[BLOCKER — do first] Fix the time-bomb `campaignSchedule` tests.** `tests/unit/campaignSchedule.test.ts` (in ThreadsDashboard source; mirrored at `apps/dashboard/`) has 3 tests that are now **deterministically failing** (failed twice on main re-run; passed earlier only because wall-clock hadn't crossed the fixtures' hardcoded dates yet): "reports campaign schedule rows with qstash state and duplicate counts", "surfaces duplicate visual risk in manager reports", "buckets accounts by safe, scheduled, and blocked states without overlap". Root cause: the test file mixes `Date.now()`-relative fixtures with HARDCODED dates (`2026-06-07`/`2026-07-07` windows, `Date.UTC(2026,5,...)`) and uses NO `vi.setSystemTime`, so the schedule-bucketing flips as real time advances. **Because `javascript` is a required check, this red blocks ALL creator-os PR merges (incl. the docs PR and Dependabot).** Fix in **ThreadsDashboard source**: freeze the clock with `vi.setSystemTime(<fixed reference consistent with the fixtures>)` in a `beforeEach` (and/or convert the hardcoded dates to `Date.now()`-relative) so the 3 tests assert stable, correct behavior; run the full TD suite several times to prove determinism; merge to TD main per its rules; then `node scripts/sync/mirror-sync.mjs --update --only apps/dashboard` and commit the re-pin. Do not just delete/skip the tests.
2. **Dependabot:** 4 safe GitHub-Actions bumps are auto-merging (CI-gated). 4 majors parked as backlog, each needs a deliberate tested migration, NOT a blind merge: creator-os #12 Tailwind v3→v4, #13 ESLint 9→10, #18 (28-dep group); ThreadsDashboard #119 (29-dep group on the live product).
3. **Frontend decomposition debt:** `Composer.tsx` (~5905 LOC) + `Autopilot.tsx` (~4390 LOC) still monolithic. Tracked in **ThreadsDashboard issue #120** with the seam map. Prerequisite before any cut: add e2e for the deep-link (`?draft=`/`?accountId=`/`?date=`) and `location.state` handoff paths (current `composer-critical.spec.ts` covers only publish). Do NOT merge a rename as a decomposition.
4. **Soak + optional delete:** 7-day soak started 2026-06-16 (earliest delete ~2026-06-23). Run the pipeline from creator-os; archived repos are the rollback (`gh repo unarchive` + anchors in `CONSOLIDATION_STATUS.md`). After a clean soak, deleting the four archived repos is owner-gated and optional (archived is harmless).

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

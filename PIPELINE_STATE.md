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

1. **[DONE 2026-06-16] `campaignSchedule` tests made deterministic.** `tests/unit/campaignSchedule.test.ts` was intermittently flaky on the `javascript` required check because it mixed `Date.now()`-relative fixtures with HARDCODED dates (`2026-06-07`/`2026-07-07` windows) and used NO `vi.setSystemTime`, so schedule-bucketing flipped with the wall-clock. Fixed in ThreadsDashboard source (TD PR #121, merged to TD main `b22aa3e5`): `vi.useFakeTimers({ toFake: ["Date"] })` + `vi.setSystemTime(new Date("2026-06-16T12:00:00.000Z"))` in `beforeEach`, `vi.useRealTimers()` in `afterEach`. Verified 30/30 ×3 runs + full TD suite (4711 passed) + typecheck/compat clean. Mirror re-pinned to TD `b22aa3e5` (creator-os PR #32); parity exit 0. No tests deleted/skipped.
2. **[DONE 2026-06-17] Manual cross-account media reuse now gated (warn-not-block).** TD PR #122 (merged to TD main `ccf1b108`, mirrored here) adds a confirmation gate on the manual publish paths (Threads + IG) in `apps/dashboard/api/_lib/handlers/posts/publish.ts` via new `manualMediaReuse.ts`. On byte-identical cross-account reuse it returns a structured `409` **before** any DB insert or Meta publish, requiring a signed short-lived override token (HMAC-SHA256, context-bound to user/platform/account/text-hash/media-fingerprint/match, 10-min TTL, timing-safe); Composer shows a confirm dialog and only sends the token on confirm; a valid override writes `posts.metadata.manual_media_reuse_override` for audit. Deliberately **warn-not-block, matching the autoposter's `needs_review` posture** — NOT a hard block, since manual publish is human-initiated. Reuses existing originality-signal/fingerprint infra (`post_originality_signals`, `instagram_account_id` column already present + populated by the originality-capture cron) so **no prod schema migration** was needed. IG matching made platform-aware (`instagram_account_id`); Threads matching byte-identical to before (autoposter not regressed). Verified independently 2026-06-17.
3. **[OWNER-DECISION — keep REELS-only] Discoverability check scoped to Reels at publish, by design.** `apps/dashboard/api/_lib/publishPreflight.ts:455` applies the off-platform discoverability check only when `igMediaType === "REELS"`. This is intentional, NOT a gap to "fix": Reels are the discovery surface Meta penalizes hardest for off-platform-link captions, whereas feed (`link in bio`) and Story (native link stickers) legitimately carry links — extending the same block to all surfaces would over-block normal posts. Campaign Factory (`core.py:21797`) applies it to all surfaces because its context differs; do NOT propagate that to the live publish path. TD PR #122 added regression coverage locking Feed/Stories as non-blocking. If the owner later wants a *soft warning* (not a block) on feed/story off-platform links, that's a separate product decision.
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

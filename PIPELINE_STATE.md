# Pipeline State

**Last updated:** 2026-06-22. This is the single source of truth for the current state of the Creator OS pipeline. It supersedes the old one-shot planning/runbook/audit docs (removed). Operational details live in `ARCHITECTURE.md`, `AGENTS.md`, and `docs/`.

## Architecture (two active product repos)

```
creator-os (this monorepo) — canonical runtime for the whole pipeline
├── apps/contentforge                  canonical (was a standalone repo)
├── python_packages/reel_factory       canonical
├── python_packages/campaign_factory   canonical
├── python_packages/reference_factory  canonical
├── packages/pipeline_contracts        shared contracts (canonical here; also its own repo)
└── tests/integration                  cross-tool integration

ThreadsDashboard (separate repo) ──deploys──▶ juno33.com   (the standalone product; permanently NOT in the monorepo)
pipeline_contracts (separate repo)                          (contracts package)
reel_factory / campaign_factory / contentforge / reference_factory  ──▶ ARCHIVED/frozen on GitHub (soak backup)
```

## What is done

- **Monorepo↔split drift: solved structurally.** One canonical copy per pipeline tool. The old dashboard mirror and no-op mirror harness were removed.
- **Consolidation (Steps 1–5) complete.** The four tools are canonical in creator-os and runnable from root (`scripts/run/*` wrappers; combined `uv run pytest` green). Their standalone repos are archived (read-only, reversible). ThreadsDashboard remains external rather than mirrored.
- **Backend audit work merged + live (independently verified 2026-06-16):** autoposter safety gates, identity/ArcFace verification + `.venv` pin (aborts loudly if provider down), inventory reservation, ingest routing (raw service-role writes gated behind a prod-disabled flag; default routes to validated Dashboard ingest), QC fail-closed (visual QC + identity block readiness; `opencv_unavailable` → not "passed"), metadata normalization (required post-render step in `reel_pipeline.py`, tested). The three backend items once falsely reported "done" (cross-account reuse, discoverability, deprecated generators) were caught by independent verification and have since been resolved — see Open work #2–#4.
- **ThreadsDashboard/juno33:** live, green on its own CI. Autoposter hardening + draft-ingest + Step G (radix unification, ui/shadcn boundary guard) shipped.
- **Governance:** branch protection on creator-os main (9 required checks, strict, enforce-admins, PR-required), gitleaks, contracts/architecture checks.
- **Track 9 rigor is landed.** PRs #189, #191, #192, and #193 completed the non-`core.py` Track-9 lift: Reference Factory intake coverage, ContentForge similarity/pipeline tests, detector calibration fixtures, and Reel Factory adapter/golden tests. The prior contract codegen/schema drift-proofing work remains protected by `pnpm check:contracts`.
- **Campaign Factory decomposition continues behind the characterization net.** Inventory planning (#186), reservations (#190), perceptual metadata (#194), and recovery (#195) are merged; continue future `core.py` work from `CORE_PY_DECOMPOSITION_PLAN.md`, one coherent operational domain per PR.

## Current health

- creator-os `main` green (the flaky `campaignSchedule` test was fixed — open work #1). TD/juno33 healthy and live.
- Branch protection is ON — all changes to creator-os main go via PR with green checks. No direct pushes, no `--no-verify`, no admin bypass.

## Open work

1. **[DONE 2026-06-16] `campaignSchedule` tests made deterministic.** `tests/unit/campaignSchedule.test.ts` was intermittently flaky on the `javascript` required check because it mixed `Date.now()`-relative fixtures with HARDCODED dates (`2026-06-07`/`2026-07-07` windows) and used NO `vi.setSystemTime`, so schedule-bucketing flipped with the wall-clock. Fixed in ThreadsDashboard source (TD PR #121, merged to TD main `b22aa3e5`): `vi.useFakeTimers({ toFake: ["Date"] })` + `vi.setSystemTime(new Date("2026-06-16T12:00:00.000Z"))` in `beforeEach`, `vi.useRealTimers()` in `afterEach`. Verified 30/30 ×3 runs + full TD suite (4711 passed) + typecheck/compat clean. No tests deleted/skipped.
2. **[DONE 2026-06-17] Manual cross-account media reuse now gated (warn-not-block).** TD PR #122 (merged to TD main `ccf1b108`) adds a confirmation gate on the manual publish paths (Threads + IG) in the ThreadsDashboard publish handler via `manualMediaReuse.ts`. On byte-identical cross-account reuse it returns a structured `409` **before** any DB insert or Meta publish, requiring a signed short-lived override token (HMAC-SHA256, context-bound to user/platform/account/text-hash/media-fingerprint/match, 10-min TTL, timing-safe); Composer shows a confirm dialog and only sends the token on confirm; a valid override writes `posts.metadata.manual_media_reuse_override` for audit. Deliberately **warn-not-block, matching the autoposter's `needs_review` posture** — NOT a hard block, since manual publish is human-initiated. Reuses existing originality-signal/fingerprint infra (`post_originality_signals`, `instagram_account_id` column already present + populated by the originality-capture cron) so **no prod schema migration** was needed. IG matching made platform-aware (`instagram_account_id`); Threads matching byte-identical to before (autoposter not regressed). Verified independently 2026-06-17.
3. **[OWNER-DECISION — keep REELS-only] Discoverability check scoped to Reels at publish, by design.** ThreadsDashboard publish preflight applies the off-platform discoverability check only when `igMediaType === "REELS"`. This is intentional, NOT a gap to "fix": Reels are the discovery surface Meta penalizes hardest for off-platform-link captions, whereas feed (`link in bio`) and Story (native link stickers) legitimately carry links — extending the same block to all surfaces would over-block normal posts. Campaign Factory applies it to all surfaces because its context differs; do NOT propagate that to the live publish path. TD PR #122 added regression coverage locking Feed/Stories as non-blocking. If the owner later wants a *soft warning* (not a block) on feed/story off-platform links, that's a separate product decision.
4. **[DONE 2026-06-17] Deprecated grok/grid/six_pack now fail closed.** creator-os PR #35 inverted the guard in `python_packages/reel_factory/deprecated_generators.py`: `guard_deprecated_generator` now raises **by default** unless a local/test operator sets `REEL_FACTORY_ALLOW_DEPRECATED_GENERATORS=1` AND `REEL_FACTORY_ENV=local|development|test` (or pytest); **prod env wins unconditionally** even with the allow flag (`_prod_env_active()` → blocked). The old `REEL_FACTORY_RAISE_ON_DEPRECATED_GENERATORS` remains block-only. Call sites closed: all five `/api/grid-crop/*` endpoints now return a controlled **410** (previously had no guard at all); `/api/references/analyze` no longer defaults `model="grok-4.3"` (missing model → **400**, any `grok*` → 410-gated); `detect_grid_status` is guarded and the **active** single-image path was rewired to a new non-deprecated `single_image_layout_status()` so fail-closed does NOT break legit generation. 320 reel_factory tests pass; independently verified.
5. **[RESOLVED 2026-06-17] Dependabot majors handled.** All four are now closed/merged — nothing pending: creator-os #12 (Tailwind v3→v4) CLOSED, #13 (ESLint 9→10) CLOSED (ignore rule added in #29), #18 (28-dep prod group) CLOSED; ThreadsDashboard #119 (29-dep prod group) MERGED + mirrored. Majors are closed rather than blind-merged on purpose — each is a breaking migration (Tailwind config rewrite, ESLint flat-config, 28/29-at-once groups). Safe GitHub-Actions bumps continue to auto-merge (CI-gated). If dependabot re-raises the closed majors next cycle, add `ignore` rules rather than merging untested.
6. **Frontend decomposition debt:** `Composer.tsx` (~5905 LOC) + `Autopilot.tsx` (~4390 LOC) still monolithic. Tracked in **ThreadsDashboard issue #120** with the seam map. Prerequisite before any cut: add e2e for the deep-link (`?draft=`/`?accountId=`/`?date=`) and `location.state` handoff paths (current `composer-critical.spec.ts` covers only publish). Do NOT merge a rename as a decomposition.
7. **Soak + optional delete:** 7-day soak started 2026-06-16 (earliest delete ~2026-06-23). Run the pipeline from creator-os; archived standalone repos remain the rollback. After a clean soak, deleting the four archived repos is owner-gated and optional (archived is harmless).
8. **[DONE 2026-06-19] Track 9 non-core rigor completed.** PR #189 raised `reference_intake.py` coverage to the target band and pinned the caption-archetype regression; PR #191 covered ContentForge similarity/pipeline blocking and advisory behavior; PR #192 pinned detector thresholds against drift; PR #193 added tested external-generation adapter failure handling plus caption/render golden tests. Remaining production-grade lift is the ongoing Campaign Factory decomposition, tracked separately.

## Owner-only (out of scope for automated agents)

- Secret rotation / OAuth re-encryption / git-history purge (P0) — provider consoles. See `docs/security/`.
- Scale proof (50/100/200 load, QStash-outage/reconciliation-drain).

## How to work here

- Fix a tool: edit it in creator-os (it's canonical now), open a PR, green checks, merge.
- Dashboard work: fix it in `/Users/aderdesouza/Developer/ThreadsDashboard`; Creator OS has no committed dashboard mirror.
- See `AGENTS.md` for agent conventions and `ARCHITECTURE.md` for system design.

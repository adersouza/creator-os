# Creator OS Simplification Plan

This is the ordered implementation sequence for the inspected code. It is not a
future architecture roadmap.

| Order | Change | Files/components | Compatibility / migration |
|---|---|---|---|
| 1 | Add real fast, affected, release, exhaustive tiers | `Makefile`, `scripts/verify_tier.py`, monorepo/security workflows | `make verify` remains compatible; PR and main workflow topology changes |
| 2 | Add a pinned production-recipe execution binding independent of Arena/Router | Campaign motion workflow/stage/worker and Reel local runtime | Arena admission remains required for automatic model selection and research |
| 3 | Replace normal root `create` surface with intent-first inputs | `scripts/creator-os`, Campaign CLI | explicit-mode `generate` remains an advanced compatibility command |
| 4 | Resolve creator image inventory, prompt, seed, model, and recipe internally | `production_lane.py` | existing campaign/source SQLite is read; no schema or production-row migration |
| 5 | Fan out `count=N` into N stable independent job identities | `production_lane.py` | no provider call in dry-run; cloud apply remains blocked without spend authorization |
| 6 | Make calibrated production recipes exception-reviewed | motion asset metadata, creative approval policy | calibration/research assets still require exact creative approval |
| 7 | Preserve ThreadsDashboard boundary ownership | existing draft ingest, publish preflight, account health | no ThreadsDashboard mutation required: publishable Creator OS drafts already avoid `approval_status=pending`; review-only drafts retain review |
| 8 | Add seven focused golden-path assertions | `test_product_golden_path.py` | fixture-only; no provider, schedule, publish, or production write |
| 9 | Retire normal-path compatibility aliases and duplicated docs | root CLI/README; historical files remain readable | no evidence deletion; larger archive moves wait for caller proof |
| 10 | Update the durable map after implementation is verified | `CREATOR_OS_SYSTEM_MAP.md` | map records production/research split, not volatile benchmark status |

Hard/soft QC migration:

- Hard blockers remain: wrong creator, corrupt media/face/body, source
  substitution, duplicate output, bad codec/duration, missing required audio,
  invalid account/publish state.
- Soft signals rank: attractiveness, naturalness, motion amount, hook strength,
  predicted engagement, minor artifacts.
- Existing thresholds not backed by calibrated false-positive/false-negative
  evidence stay in calibration/research until reclassified; this tranche does
  not silently weaken a live publication boundary.

Rollback:

- The production recipe path is additive and fingerprint-bound.
- The Arena/Router research path is unchanged and can be used independently.
- The old `generate` implementation command remains available for developer and
  historical use.
- No schema, database, provider, scheduling, publishing, or runtime migration is
  part of this branch.


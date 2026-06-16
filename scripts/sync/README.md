# Mirror sync + parity gate (WS1)

Fixes the monorepo↔split **drift** problem permanently: it makes it impossible for the
monorepo's copy of a project to silently diverge from the live split repo (the bug that
made fixes read "done" while production stayed unpatched).

## The model

- **Source of truth = the split repos** (`../ThreadsDashboard`, `../reel_factory`,
  `../campaign_factory`, `../contentforge`, `../reference_factory`). These are the live
  runtime.
- **The monorepo `apps/*` and `python_packages/*` are GENERATED, read-only mirrors.**
  Never hand-edit them. Edit the source split repo, then regenerate the mirror.
- **`packages/pipeline_contracts` is the exception** — it is canonical in the monorepo and
  flows the other way. It is intentionally NOT a mirror and is excluded from this tooling.
- **ThreadsDashboard is permanently standalone** (see `MONOREPO_MIGRATION_MASTER_PLAN.md`);
  its mirror is for cross-pipeline contract tests only and is never deployed.

## Files

- `../../mirror-sources.json` — the mirror map: each `mirrorPath` ← `sourceRepoPath` at a
  pinned `sourceCommit`, plus `excludeDefault` (runtime/data never mirrored).
- `mirror-lib.mjs` — shared logic (list/read source at SHA, materialize, hash, diff).
- `mirror-sync.mjs` — regenerate mirrors from source.
- `check-mirror-parity.mjs` — the gate: fails if any mirror differs from its source.
- `prepare-ci-mirror-sources.mjs` — CI helper: clones each `sourceRepoUrl` beside the
  checkout and checks out the pinned `sourceCommit` before parity runs.

## Commands

```bash
# See drift without changing anything (CI uses this until baseline is reconciled):
pnpm check:mirror-parity:report

# Enforce parity (exit 1 on any drift) — the blocking gate:
pnpm check:mirror-parity

# Regenerate a single mirror from its pinned source SHA:
node scripts/sync/mirror-sync.mjs --only python_packages/reel_factory

# Regenerate all mirrors:
pnpm sync:mirrors

# Bump pinned SHAs to each source repo's current main HEAD, then regenerate:
node scripts/sync/mirror-sync.mjs --update

# Dry-run (materialize to a temp dir, change nothing):
node scripts/sync/mirror-sync.mjs --dry-run
```

## Normal workflow after this lands

1. Fix a bug in the **source split repo** (e.g. `../campaign_factory`), commit, push.
2. In the monorepo: `node scripts/sync/mirror-sync.mjs --update --only python_packages/campaign_factory`.
3. Commit the regenerated mirror + the bumped SHA in `mirror-sources.json`.
4. `pnpm check:mirror-parity` passes. CI stays green.

If anyone hand-edits a mirror, `check:mirror-parity` fails and names the file — the edit
must move to the source repo instead.

## Rollout (staged — current status)

The gate is in **report-only** mode in CI right now because the existing mirrors are
~2,100 files out of parity (historical divergence + committed junk like `__pycache__/`,
`*.egg-info/`). Flipping to blocking before reconciling would red-wall every build.

**To finish WS1 (separate, careful step):**
1. Decide, per mirror, the canonical source branch (usually each split repo's `main`).
2. Run `pnpm sync:mirrors` to regenerate a clean baseline.
3. Review the diff (the `apps/dashboard` "changed" set includes monorepo-workspace files —
   confirm none are intentional monorepo-only config before overwriting; if some are, add
   them to that mirror's `exclude`).
4. Commit the reconciled baseline.
5. Flip CI from `check:mirror-parity:report` to `check:mirror-parity` (blocking).

## CI auth

Locally the script reads the sibling split repos directly. In CI (where the split repos
aren't checked out next to the monorepo) provide read access via a token secret
`MIRROR_SYNC_TOKEN`; `prepare-ci-mirror-sources.mjs` uses each mirror's `sourceRepoUrl`
and `sourceCommit` to recreate the sibling layout before running the blocking parity
check. ThreadsDashboard is private — the token must have read scope on it.

# Creator OS Runtime Promotion

Creator OS `main` is the canonical integration source for Campaign Factory,
Reel Factory, Reference Factory, ContentForge, Pipeline Contracts, Creator OS
Core, and repository tooling. Runtime promotion is still explicit: the pinned
machine checkout does not move merely because source code merges.

ThreadsDashboard remains a separate product repository and deployment. Creator
OS promotion must never repoint, rebuild, or deploy ThreadsDashboard.

## Current Source And Runtime Model

```text
Creator OS source
  /Users/aderdesouza/Developer/creator-os
  reviewed branches and canonical origin/main

Creator OS machine runtime
  /Users/aderdesouza/Developer/creator-os-runtime
  clean pinned checkout promoted to one reviewed Creator OS commit

ThreadsDashboard product source/runtime
  /Users/aderdesouza/Developer/ThreadsDashboard
  external UI, account, scheduling, publishing, and analytics owner

Machine state
  ~/.creator-os/
  credentials, SQLite databases, artifacts, models, logs, and evidence
```

The old component split repositories are historical rollback/source context,
not the current Creator OS control plane. Do not run modern operations from a
split-repo checkout merely because an old promotion document names it.

## Four Separate Claims

1. **Source verified:** local checks pass for an exact candidate commit.
2. **Source merged:** required CI passes for the exact commit on `main`.
3. **Runtime promoted:** the clean pinned runtime is deliberately moved to that
   exact commit after backup and preflight evidence.
4. **Operationally proven:** bounded live/read-only or separately authorized
   operations produce the expected receipts and state transitions.

None of these claims implies another. In particular, a merged commit is not a
runtime promotion, and a read-only handshake is not publication proof.

## CI Gates Before Promotion

The canonical repository-root workflows own CI and security:

- `.github/workflows/monorepo-ci.yml`
- `.github/workflows/security.yml`
- `.github/workflows/scorecard.yml`

Package-local `.github/workflows/` copies are intentionally absent because
GitHub does not execute them in this monorepo.

Before promotion, the exact candidate must pass:

```bash
make verify
pnpm security:secrets
git diff --check
```

Required CI must also be green for the exact merged commit. Path-filtered job
skips are not failures, but a local pass never substitutes for a failed or
missing required check.

## Production Promotion Checklist

### 1. Establish exact identity

- Fetch `origin/main` and record the exact target SHA.
- Confirm the target is reviewed and merged with required CI green.
- Confirm the source worktree and pinned runtime checkout separately.
- Refuse promotion from a dirty, ambiguous, or unreviewed checkout.

### 2. Protect machine state

- Create a fresh structured runtime backup.
- Verify SQLite integrity and private file permissions.
- Complete the documented temporary restore drill.
- Preserve operational databases, media, models, receipts, and migration
  evidence; source cleanup never authorizes deleting them.

### 3. Re-run source and read-only gates

- Run `make verify` from the exact target source.
- Run `scripts/creator-os status --json` before changing the runtime.
- If live seam verification is needed, run only
  `status --live-read-only --json`; confirm zero product rows, provider jobs,
  and cost events.
- Treat provider, ThreadsDashboard, or account warnings as explicit blockers or
  warnings according to their actual gate—never as an implicit pass.

### 4. Promote only the pinned runtime

- Move `/Users/aderdesouza/Developer/creator-os-runtime` to the exact approved
  Creator OS commit using the supported runtime-promotion procedure.
- Do not modify the developer source checkout as a promotion shortcut.
- Do not copy databases or generated artifacts into the Git checkout.
- Do not change credentials, schedules, posts, QStash, accounts, provider
  state, or ThreadsDashboard deployment as part of source promotion.

### 5. Verify post-promotion identity

- Confirm the runtime checkout is clean and exactly matches the approved SHA.
- Run `scripts/creator-os status --json` from the pinned runtime.
- Re-run the read-only live probe only when configured and appropriate.
- Verify LaunchAgent command paths still resolve to the pinned runtime and
  canonical state roots.
- Record the source SHA, runtime SHA, backup identity, status output, and trace
  IDs in dated evidence under `~/.creator-os/analysis/`.

### 6. Prove operations separately

Runtime promotion does not authorize generation, export, scheduling, or
publishing. Each later operation keeps its own approvals and evidence:

- paid generation: explicit mode, target, confirmation, and finite cap;
- draft export: bounded approved assets and validated payloads;
- scheduling/publishing: ThreadsDashboard authorization and downstream proof;
- learning: genuine Instagram publication identity and metric-history rows.

## Component Boundaries During Promotion

### ContentForge

- Verify the headless CLI and current audit contracts.
- Do not introduce a daemon, job service, or publishing authority.
- Preserve generated audit output outside Git.

### Campaign, Reel, And Reference

- Promote the monorepo packages together at one reviewed Creator OS SHA.
- Preserve Campaign as the sole control plane and Reel/Reference as workers.
- Do not revive split-repo CLIs, flat facades, retired grid workflows, or
  package-local CI as rollback mechanisms.

### Dashboard

- Dashboard production deployment must stay on the external ThreadsDashboard
  repository unless the owner explicitly changes that architecture.
- Validate shared contract snapshots across repositories before dependent
  changes merge or deploy.
- Never point a Dashboard Vercel project at Creator OS; Creator OS has no
  product dashboard application.

## Rollback

- Record the previously promoted Creator OS runtime SHA before promotion.
- Roll back the pinned runtime to that exact reviewed SHA; do not patch runtime
  files in place.
- Keep canonical state and credentials unchanged unless the incident itself is
  a state or credential incident with separately approved recovery steps.
- After rollback, run status and read-only verification again and record the
  result.
- Do not use historical split repositories as an automatic rollback path; they
  are not guaranteed to match current contracts or state layout.

## Promotion Blockers

Stop before changing the pinned runtime when any of these are true:

- target commit is not exact, reviewed, merged, or CI-green;
- source or runtime checkout is dirty or ambiguous;
- backup, SQLite integrity, permissions, or restore proof is missing;
- canonical contracts or the external ThreadsDashboard snapshot drift;
- source verification fails;
- the requested operation would also mutate production data, providers,
  schedules, posts, accounts, credentials, or deployment routing without its
  own explicit authorization.

This document defines the promotion procedure. It intentionally contains no
hard-coded “current” SHA, account count, inventory count, or provider balance;
those values drift and must come from fresh evidence.

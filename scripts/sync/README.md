# Mirror Sync Legacy Harness

Creator OS no longer commits split-repo mirrors. The four pipeline tools and
`packages/pipeline_contracts` are canonical in this monorepo. ThreadsDashboard
is external and remains in `/Users/aderdesouza/Developer/ThreadsDashboard` or an
explicit `THREADSDASH_ROOT`.

## Current Model

- `mirror-sources.json` intentionally has an empty `mirrors` array.
- The old mirror parity scripts succeed when no mirrors are configured, but they
  are not active audit or CI gates.
- `prepare-ci-mirror-sources.mjs` is kept for compatibility and exits cleanly
  when no source repos need cloning.

This keeps old CI/script entrypoints stable while removing the confusing
committed dashboard copy.

## Dashboard Boundary

Dashboard source changes, visual regression, typecheck, publish preflight, and
deployment provenance belong to the ThreadsDashboard repository. Creator OS
validates only the pipeline contracts and handoff payload shape.

## Legacy Commands

```bash
node scripts/sync/check-mirror-parity.mjs
node scripts/sync/check-mirror-parity.mjs --report
node scripts/sync/mirror-sync.mjs
```

All three commands are safe in the no-mirror state, but green output only means
there are no configured committed mirrors to compare.

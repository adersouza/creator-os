# Mirror Sync Compatibility Harness

Creator OS no longer commits split-repo mirrors. The four pipeline tools and
`packages/pipeline_contracts` are canonical in this monorepo. ThreadsDashboard
is external and remains in `/Users/aderdesouza/Developer/ThreadsDashboard` or an
explicit `THREADSDASH_ROOT`.

## Current Model

- `mirror-sources.json` intentionally has an empty `mirrors` array.
- `pnpm check:mirror-parity` succeeds when no mirrors are configured.
- `pnpm sync:mirrors` is a no-op when no mirrors are configured.
- `prepare-ci-mirror-sources.mjs` is kept for compatibility and exits cleanly
  when no source repos need cloning.

This keeps old CI/script entrypoints stable while removing the confusing
committed `apps/dashboard` copy.

## Dashboard Boundary

Dashboard source changes, visual regression, typecheck, publish preflight, and
deployment provenance belong to the ThreadsDashboard repository. Creator OS
validates only the pipeline contracts and handoff payload shape.

## Commands

```bash
pnpm check:mirror-parity
pnpm check:mirror-parity:report
pnpm sync:mirrors
```

All three commands are safe in the no-mirror state.

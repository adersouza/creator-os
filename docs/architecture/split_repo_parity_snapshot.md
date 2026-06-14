# Split Repo Parity Snapshot

Captured locally during the monorepo promotion-prep pass and refreshed after
the split-repo cleanup/merge pass.

| Split repo | Branch | HEAD | Status |
|---|---:|---:|---|
| `pipeline_contracts` | `main` | `034806a` | clean, merged docs-only agent notes |
| `contentforge` | `main` | `b73a282` | clean, merged docs-only agent notes |
| `reference_factory` | `main` | `2cf59f2` | clean, merged docs/runbook boundary notes |
| `campaign_factory` | `main` | `0f31681` | clean, merged repaired repurposer + docs |
| `reel_factory` | `main` | `a4161d5` | clean, merged direct-reference simplification |
| `ThreadsDashboard` | `main` | `9147ae897` | clean, merged UI/layout, interaction polish, analytics narrative, and composer/calendar polish |

## Parity Assessment

The monorepo has passing package, app, contract, and integration gates on the
latest `codex/creator-os-import-repair` commit. The split repos no longer have
local dirty runtime work; intentional changes are merged to each repo's
`main`.

This is source parity, not production runtime promotion:

- `creator-os` is still a promotion candidate until PR #1 lands.
- Deployment routing is still explicit and should not be moved automatically.
- Smart-link hardening remains intentionally separate on
  `origin/codex/smart-link-hardening`; it was not mixed into the UI/layout
  branch.

## Required Before Final Promotion

1. Keep generated media, DB files, local model weights, caches, and output
   folders out of source.
2. Merge `creator-os` PR #1 after the latest monorepo CI remains green.
3. Run staged operational dry-run proof from monorepo only after explicit
   approval.

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
| `ThreadsDashboard` | `main` | `195654ba3` | clean, merged UI/layout, interaction polish, analytics narrative, composer/calendar polish, smart-link hardening, Calendar metric responsiveness, and autoposter alert false-positive fix |

## Parity Assessment

The monorepo has passing package, app, contract, and integration gates on
`creator-os/main`. The split repos no longer have local dirty runtime work;
intentional changes are either merged to each repo's `main` or preserved on
separate review branches.

This is source parity, not production runtime promotion:

- `creator-os/main` is merged and CI-green as the source integration baseline.
- Deployment routing is still explicit and should not be moved automatically.
- Smart-link hardening is present in ThreadsDashboard `main`; the newer
  bento-dashboard UI branch remains separate on
  `origin/codex/dashboard-pending-ui-and-cap-review`.

## Required Before Final Promotion

1. Keep generated media, DB files, local model weights, caches, and output
   folders out of source.
2. Run staged operational dry-run proof from monorepo only after explicit
   approval.

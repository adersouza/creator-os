# Split Repo Parity Snapshot

Captured locally during the monorepo promotion-prep pass and refreshed after
the split-repo cleanup/push pass.

| Split repo | Branch | HEAD | Status |
|---|---:|---:|---|
| `pipeline_contracts` | `codex/pipeline-contracts-agent-notes` | `9522ebe` | clean, pushed docs-only agent notes |
| `contentforge` | `codex/contentforge-agent-notes` | `031168f` | clean, pushed docs-only agent notes |
| `reference_factory` | `codex/reference-factory-agent-notes` | `21c0d0f` | clean, pushed docs/runbook boundary notes |
| `campaign_factory` | `codex/promote-repurposer` | `4073ead` | clean, pushed repaired repurposer + docs |
| `reel_factory` | `codex/local-vlm-prompting-pipeline` | `5832fab` | clean, pushed direct-reference simplification |
| `ThreadsDashboard` | `codex/autoposter-aesthetic-filler-hotfix` | `c2abe2bc1` | clean, pushed UI/layout branch |

## Parity Assessment

The monorepo has passing package, app, contract, and integration gates on the
latest `codex/creator-os-import-repair` commit. The split repos no longer have
local dirty runtime work; intentional changes are committed and pushed to
focused branches.

This is branch-level parity, not production runtime promotion:

- Most split repo work is still on `codex/*` branches, not merged to each
  repo's `main`.
- `creator-os` is still a promotion candidate until PR #1 lands and deployment
  routing is explicitly moved.
- Smart-link hardening remains intentionally separate on
  `origin/codex/smart-link-hardening`; it was not mixed into the UI/layout
  branch.

## Required Before Final Promotion

1. Merge or accept the split repo `codex/*` branches that should remain runtime
   baselines.
2. Keep generated media, DB files, local model weights, caches, and output
   folders out of source.
3. Merge `creator-os` PR #1 after the latest monorepo CI remains green.
4. Run staged operational dry-run proof from monorepo only after explicit
   approval.

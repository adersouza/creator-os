# Consolidation Status

Date: 2026-06-16

## Current State

- Steps 1-2 are complete on creator-os `main` at `1216d31953b510f91fb6239bf3ad8b145c910e52`.
- Step 3 repointed the owner-approved active surfaces:
  - `contentforge/start.sh` now launches `/Users/aderdesouza/Developer/creator-os/scripts/run/contentforge`.
  - Campaign Factory default roots now point at creator-os pipeline paths.
  - Campaign Factory operator command output now uses `/Users/aderdesouza/Developer/creator-os/scripts/run/*`.
- Step 4 flipped source-of-truth for `apps/contentforge`, `python_packages/reel_factory`, `python_packages/campaign_factory`, and `python_packages/reference_factory`; they are canonical creator-os source trees.
- No committed read-only mirrors remain. ThreadsDashboard remains standalone and is not consolidated.
- Step 5 archive is complete for the four pipeline split repos. No repositories were deleted.
- PR #20 merge commit `85d4977fd488db46147b194eb74d23ccd43e4f36` is on `origin/main`; `git merge-base --is-ancestor 85d4977fd488db46147b194eb74d23ccd43e4f36 origin/main` returned `0`.
- Soak started on 2026-06-16. Delete remains owner-gated after the 7-day soak.

## Split Repo Repoint Commits

| Repo | Pre-repoint main SHA | Repoint main SHA | Notes |
| --- | --- | --- | --- |
| `contentforge` | `6affefd2cca96c2eaca81e433d0621a8919f02bf` | `624fbe6da2351f7b63b442da7ba57e9ac2d026a4` | `start.sh` delegates to creator-os wrapper. |
| `campaign_factory` | `978f886af287093c176e73b3de8393a77a5fffd1` | `5134cebdf8ea71fb7c57e9f4fa03a2836074fde4` | Defaults and operator commands point at creator-os. |
| `reel_factory` | `a9b3029bc92ff0de7d3ec994b48ffb9ff9797136` | No Step 3 active runner change required | Archived in Step 5. |
| `reference_factory` | `5e8bfa73522700a54c85782643a35c75f82dd2ff` | No Step 3 active runner change required | Archived in Step 5. |

## Archive Results

| Repo | Canonical creator-os path | Pre-archive rollback SHA | ARCHIVED.md commit SHA | `isArchived` |
| --- | --- | --- | --- | --- |
| `reel_factory` | `python_packages/reel_factory` | `a9b3029bc92ff0de7d3ec994b48ffb9ff9797136` | `efebe76e1d2f39cfc7c7050171dab2d553b06a19` | `true` |
| `campaign_factory` | `python_packages/campaign_factory` | `5134cebdf8ea71fb7c57e9f4fa03a2836074fde4` | `107091eed3261faf235d7ff197c7d08cf80fc1f1` | `true` |
| `contentforge` | `apps/contentforge` | `624fbe6da2351f7b63b442da7ba57e9ac2d026a4` | `d50cc6d45f37c5de7989840e9aae3db6e7291ff5` | `true` |
| `reference_factory` | `python_packages/reference_factory` | `5e8bfa73522700a54c85782643a35c75f82dd2ff` | `41b7ae70b2d7c88a72aab7b66707ed1539854b99` | `true` |

Confirmed non-target repositories remain unarchived:

- `ThreadsDashboard`: `false`
- `creator-os`: `false`
- `pipeline_contracts`: `false`

## Verification Evidence

- Active runner grep over `apps/contentforge/start.sh` and `python_packages/campaign_factory/campaign_factory/control.py`: pass, no standalone active runner paths found.
- `scripts/run/contentforge test`: pass, 81 passed.
- `scripts/run/campaign-factory doctor`: pass, `ok: true`, `blockingCount: 0`, `warningCount: 2`; emitted commands all use `/Users/aderdesouza/Developer/creator-os/scripts/run/*`.
- `uv run pytest python_packages/reel_factory/tests python_packages/campaign_factory/tests python_packages/reference_factory/tests tests/integration`: pass, 795 passed, 48 warnings.
- `pnpm --filter contentforge test`: pass, 81 passed.
- `pnpm check:mirror-parity`: pass; no committed mirrors configured.
- `git diff --check`: pass.
- `graphify update .`: pass, rebuilt 26330 nodes, 60403 edges, 1376 communities.

## Archive Verification Evidence

- `git diff --check`: passed in each split repo before the archive notice commit.
- `gh repo archive adersouza/reel_factory --yes`: completed; `isArchived` confirmed `true`.
- `gh repo archive adersouza/campaign_factory --yes`: completed; `isArchived` confirmed `true`.
- `gh repo archive adersouza/contentforge --yes`: completed; `isArchived` confirmed `true`.
- `gh repo archive adersouza/reference_factory --yes`: completed; `isArchived` confirmed `true`.

## Rollback Map

- Creator-os Step 3/4 rollback: open a creator-os PR reverting the Step 3/4 merge commit and restoring the four removed `mirror-sources.json` entries plus mirror provenance files.
- `contentforge` repoint rollback: `git -C /Users/aderdesouza/Developer/contentforge revert 624fbe6da2351f7b63b442da7ba57e9ac2d026a4`, then push `main`.
- `campaign_factory` repoint rollback: `git -C /Users/aderdesouza/Developer/campaign_factory revert 5134cebdf8ea71fb7c57e9f4fa03a2836074fde4`, then push `main`.
- `reel_factory` archive rollback: `gh repo unarchive adersouza/reel_factory`, then `git -C /Users/aderdesouza/Developer/reel_factory revert efebe76e1d2f39cfc7c7050171dab2d553b06a19` and push `main`.
- `campaign_factory` archive rollback: `gh repo unarchive adersouza/campaign_factory`, then `git -C /Users/aderdesouza/Developer/campaign_factory revert 107091eed3261faf235d7ff197c7d08cf80fc1f1` and push `main`.
- `contentforge` archive rollback: `gh repo unarchive adersouza/contentforge`, then `git -C /Users/aderdesouza/Developer/contentforge revert d50cc6d45f37c5de7989840e9aae3db6e7291ff5` and push `main`.
- `reference_factory` archive rollback: `gh repo unarchive adersouza/reference_factory`, then `git -C /Users/aderdesouza/Developer/reference_factory revert 41b7ae70b2d7c88a72aab7b66707ed1539854b99` and push `main`.

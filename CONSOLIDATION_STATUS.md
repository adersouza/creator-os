# Consolidation Status

Date: 2026-06-16

## Current State

- Steps 1-2 are complete on creator-os `main` at `1216d31953b510f91fb6239bf3ad8b145c910e52`.
- Step 3 repointed the owner-approved active surfaces:
  - `contentforge/start.sh` now launches `/Users/aderdesouza/Developer/creator-os/scripts/run/contentforge`.
  - Campaign Factory default roots now point at creator-os pipeline paths.
  - Campaign Factory operator command output now uses `/Users/aderdesouza/Developer/creator-os/scripts/run/*`.
- Step 4 flips source-of-truth for `apps/contentforge`, `python_packages/reel_factory`, `python_packages/campaign_factory`, and `python_packages/reference_factory`; they are canonical creator-os source trees after this PR merges.
- `apps/dashboard` remains the only read-only mirror. ThreadsDashboard remains standalone and is not consolidated.
- Step 5 archive is pending owner merge of this Step 3/4 creator-os PR. No repositories have been archived in this PR.

## Split Repo Repoint Commits

| Repo | Pre-repoint main SHA | Repoint main SHA | Notes |
| --- | --- | --- | --- |
| `contentforge` | `6affefd2cca96c2eaca81e433d0621a8919f02bf` | `624fbe6da2351f7b63b442da7ba57e9ac2d026a4` | `start.sh` delegates to creator-os wrapper. |
| `campaign_factory` | `978f886af287093c176e73b3de8393a77a5fffd1` | `5134cebdf8ea71fb7c57e9f4fa03a2836074fde4` | Defaults and operator commands point at creator-os. |
| `reel_factory` | `a9b3029bc92ff0de7d3ec994b48ffb9ff9797136` | Pending archive notice after owner merge | No Step 3 active runner change required. |
| `reference_factory` | `5e8bfa73522700a54c85782643a35c75f82dd2ff` | Pending archive notice after owner merge | No Step 3 active runner change required. |

## Verification Evidence

- Active runner grep over `apps/contentforge/start.sh` and `python_packages/campaign_factory/campaign_factory/control.py`: pass, no standalone active runner paths found.
- `scripts/run/contentforge test`: pass, 81 passed.
- `scripts/run/campaign-factory doctor`: pass, `ok: true`, `blockingCount: 0`, `warningCount: 2`; emitted commands all use `/Users/aderdesouza/Developer/creator-os/scripts/run/*`.
- `uv run pytest python_packages/reel_factory/tests python_packages/campaign_factory/tests python_packages/reference_factory/tests tests/integration`: pass, 795 passed, 48 warnings.
- `pnpm --filter contentforge test`: pass, 81 passed.
- `pnpm check:mirror-parity`: pass, only `apps/dashboard` checked, missing=0 changed=0 extra=0.
- `git diff --check`: pass.
- `graphify update .`: pass, rebuilt 26330 nodes, 60403 edges, 1376 communities.

## Archive Plan

Archive will run only after the owner merges the Step 3/4 PR:

1. Confirm the Step 3/4 branch tip is an ancestor of `origin/main`.
2. Add `ARCHIVED.md` to each split repo root with:
   `Canonical home is creator-os/<path>. Read-only, do not commit. Archived on 2026-06-16. Delete decision after 7-day soak by owner only.`
3. Commit and push each split repo `main`.
4. Run `gh repo archive adersouza/<repo> --yes` for only:
   - `reel_factory`
   - `campaign_factory`
   - `contentforge`
   - `reference_factory`
5. Confirm each archive with `gh repo view adersouza/<repo> --json isArchived`.
6. Open a second creator-os status PR with actual archive SHAs and confirmations.

## Rollback Map

- Creator-os Step 3/4 rollback: open a creator-os PR reverting the Step 3/4 merge commit and restoring the four removed `mirror-sources.json` entries plus mirror provenance files.
- `contentforge` repoint rollback: `git -C /Users/aderdesouza/Developer/contentforge revert 624fbe6da2351f7b63b442da7ba57e9ac2d026a4`, then push `main`.
- `campaign_factory` repoint rollback: `git -C /Users/aderdesouza/Developer/campaign_factory revert 5134cebdf8ea71fb7c57e9f4fa03a2836074fde4`, then push `main`.
- Archive rollback after Step 5: `gh repo unarchive adersouza/<repo>`, then revert the repo's `ARCHIVED.md` commit.

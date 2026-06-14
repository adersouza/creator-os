# Split Repo Parity Snapshot

Captured locally during the monorepo promotion-prep pass.

| Split repo | Branch | HEAD | Status |
|---|---:|---:|---|
| `pipeline_contracts` | `main` | `d6a5890` | dirty: untracked `AGENTS.md` |
| `contentforge` | `main` | `f8c13d4` | dirty: untracked `AGENTS.md` |
| `reference_factory` | `main` | `08be87f` | dirty: modified `RUNBOOK.md`, untracked `AGENTS.md` |
| `campaign_factory` | `codex/promote-repurposer` | `5321b68` | dirty: modified `RUNBOOK.md`, untracked `AGENTS.md` |
| `reel_factory` | `codex/local-vlm-prompting-pipeline` | `bba83dc` | dirty: active direct-reference simplification changes |
| `ThreadsDashboard` | `codex/autoposter-aesthetic-filler-hotfix` | `9a635c4bc` | dirty: active UI/layout changes |

## Parity Assessment

The monorepo has passing package, app, contract, and integration gates, but final
split-repo parity is not clean enough to declare the monorepo the production
source of truth yet.

The blockers are operational hygiene, not failing monorepo tests:

- Split repos have local dirty changes that need separate commit/review decisions.
- `ThreadsDashboard` is ahead of `origin/main` on a feature branch.
- `reel_factory` has active direct-reference workflow changes that should be reconciled deliberately.
- `campaign_factory` has the promoted `repurposer` branch active.

## Required Before Final Promotion

1. Commit or intentionally discard dirty split-repo changes.
2. Merge accepted split-repo repair branches.
3. Re-import or verify those heads against the matching monorepo package/app folders.
4. Rerun monorepo CI.
5. Run staged operational dry-run proof from monorepo only after explicit approval.

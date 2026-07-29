# Campaign Factory Agent Notes

Campaign Factory is the Creator OS control brain. It owns campaign state, readiness, inventory discipline, learning reports, draft payloads, and cross-repo orchestration.

## Current Cross-Repo Truth

- Reel Factory active generation path is direct Higgsfield reference-image
  stills at `9:16`. Campaign Factory resolves and passes the pinned Stacey,
  Larissa, or Lola Soul ID; it must never reuse one creator's identity for
  another.
- Grok/Qwen/Ollama/Florence visual-schema and grid/cropped-panel workflows are legacy Reel Factory experiments, not the current production path.
- ContentForge owns variant/audit mechanics.
- ThreadsDashboard owns real app posts, schedules, publishing infrastructure, account data, and analytics.
- Pipeline Contracts owns schemas, not business logic.

## Do Not Do

- Do not publish directly.
- Do not schedule or export drafts unless explicitly requested.
- Do not mutate account health, metrics, or production inventory during audits/docs work.
- Do not bypass Reel Factory lineage or ThreadsDashboard preflight/readiness checks.

## Notes

The `repurposer/` module is isolated. It is not wired into production scheduling, publishing, inventory, or Campaign Factory registration flows unless explicitly requested.

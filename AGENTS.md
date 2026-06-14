# Creator OS Agent Notes

This monorepo is a repaired import/reconciliation workspace. The deployable runtime baseline is still the split repos under `/Users/aderdesouza/Developer` unless the user explicitly promotes the monorepo.

## Current Runtime Truth

- `reel_factory`: active creative generation path is direct Higgsfield reference-image generation, not Grok/grid.
- `campaign_factory`: campaign control brain, readiness, inventory, learning, draft export.
- `contentforge`: variant generation, FFmpeg processing, similarity/readiness/forensics audits.
- `ThreadsDashboard`: product UI, Supabase data, drafts, scheduling, publishing infrastructure, analytics.
- `pipeline_contracts`: shared schemas and validators.
- `reference_factory`: reference review, gold learning set, pattern/audio exports.

## Contract Ownership

`packages/pipeline_contracts` is the canonical source for shared schemas,
Python validators, and TypeScript exports inside this monorepo. Compatibility
copies under `pipeline_contracts/`, `apps/dashboard/pipeline_contracts/`, and
`python_packages/campaign_factory/schemas/` must stay byte-for-byte synced with
the package source. Run `pnpm check:contracts` after any contract or payload
change.

## Reel Factory Active Path

```text
single-person reference image
→ Higgsfield direct reference-image still
→ Stacey Soul ID d63ea9c7-b2c7-439c-bf0c-edfdf9938a36
→ one 9:16 still
→ captured Higgsfield prompt + lineage
→ optional append-only body emphasis
→ accepted still
→ deterministic Kling motion prompt
```

Grok, Qwen/Ollama/Florence, visual-schema, grids, cropped panels, and `_grok.json` are legacy/experimental unless explicitly requested.

## Do Not Touch During Docs/Integration Work

- Scheduling
- Publishing
- QStash
- Account health
- Metrics sync
- Production inventory state
- ThreadsDashboard runtime posting paths

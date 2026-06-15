# Creator OS Agent Notes

This monorepo is a repaired import/reconciliation workspace. The deployable runtime baseline is still the split repos under `/Users/aderdesouza/Developer` unless the user explicitly promotes the monorepo.

## Promotion Status

`creator-os/main` is the CI-green source integration baseline. It is not yet
the production runtime source. A non-mutating staged acceptance run from the
monorepo path against a copied Campaign Factory SQLite database certified the
25-account gate and blocked the 50-account gate on inventory buffer only.

Do not promote production deployments from this repo without an explicit
deployment instruction. In particular, `apps/dashboard/vercel.json` includes
scheduler and publishing cron entries, so Dashboard runtime promotion must be
intentional and reviewed.

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

## Tooling And PR Safety

- Use GitHub Actions logs/checks before guessing at PR failures.
- CodeQL and TruffleHog run from `.github/workflows/security.yml`.
- Use `pnpm security:secrets` for local secret scanning when `gitleaks` or
  `trufflehog` is installed.
- Use `pnpm test:visual` for Dashboard Storybook visual regression checks.
- Use `pnpm check:artifacts` before committing tooling or generated-output
  changes.
- Use `pnpm check:arch` before merging changes that cross app/package
  boundaries. It runs dependency-cruiser for TypeScript and import-linter for
  Python.
- See `docs/architecture/tooling_hardening.md` for dependency-update,
  visual-regression, Sentry, and Graphify operating rules.
- See `docs/architecture/github_protection_settings.md` for GitHub rulesets,
  merge queue, protected environments, and Secret Protection settings that must
  be configured outside the repo.

## Graphify

If `graphify-out/graph.json` exists and the task is an architecture or
codebase-relationship question, query Graphify before broad source browsing:

```bash
graphify query "How does Campaign Factory hand off to ThreadsDashboard?"
```

Run `pnpm graphify:update` after code changes. `graphify-out/` is local
architecture output and must not be committed unless explicitly approved.

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

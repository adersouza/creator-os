# Creator OS

Creator OS is a contract-driven, headless content-production monorepo. It
creates and judges media, prepares validated drafts, and learns from measured
performance. It does not own the product UI, account management, scheduling, or
publishing; those belong to the external ThreadsDashboard repository and
[juno33.com](https://juno33.com).

The durable architecture and runtime map is
[`CREATOR_OS_SYSTEM_MAP.md`](./CREATOR_OS_SYSTEM_MAP.md). Current operational
truth is tracked in [`PIPELINE_STATE.md`](./PIPELINE_STATE.md).

## Pipeline

```text
reference intake
  -> Reference Factory analysis and human labels
  -> reference bank, patterns, prompts, and audio recommendations
  -> Campaign Factory creative plan
  -> Reel Factory generation and lineage
  -> ContentForge headless QC and blocking evidence
  -> Campaign Factory readiness and contract validation
  -> HMAC-signed draft-only handoff
  -> ThreadsDashboard approval, schedule, and publish
  -> performance history
  -> Campaign/Reel/Reference learning fan-out
```

| Component | Owns | Does not own |
|---|---|---|
| Reference Factory | reference intake, labels, winner patterns, prompt packs, audio recommendations | campaign decisions or publishing |
| Reel Factory | Soul stills, static MP4s, optional motion/Kling, caption placement/rendering, media lineage | account routing or publishing |
| Campaign Factory | campaign plans, inventory, readiness, spend gates, QC requests, draft payloads, learning ingestion | product UI or platform publishing |
| ContentForge | PDQ/SSCD distinctness, OCR, safe zones, readability, watchability, media evidence and verdicts | campaign policy |
| Pipeline Contracts | canonical JSON schemas, Python validation, generated TypeScript | business decisions |
| ThreadsDashboard | product UI, Supabase, accounts, approvals, scheduling, publishing, analytics | Creator OS generation internals |

`creator_os_core` contains only shared authentication, atomic file operations,
SQLite, vector, media-probe, runtime-path, and global runtime-guard helpers.

## Active Creative Path

The normal image path is one reference image through Higgsfield Soul V2 with an
explicit Soul ID. The reference-conditioned result captures the composition
prompt and lineage. An accepted still always receives a local, zero-provider-
cost static MP4. Motion edit is optional and local. Kling is optional, paid,
and reserved for an explicitly approved best candidate.

Overlay text always goes through Reel Factory placement and caption rendering.
If no safe lane exists, no overlay is forced. Native platform audio is carried
as `audio_intent.v1`; it is not burned into the MP4.

Grok, grid/cropped-panel, Qwen, Ollama, Florence, and visual-schema generation
are not normal operator paths. A small number of legacy helpers remain only
where current imports or fail-closed compatibility guards still require them.

## One Operator Command

Use `scripts/creator-os` (or `pnpm creator-os -- ...`) for supported operator
workflows:

```bash
# Read-only: repository, contracts, config, runtime, DB, and explicit NOT_RUN checks
scripts/creator-os status

# Read-only fixture-backed integrity audit
scripts/creator-os doctor --quick

# Local reference/audio refresh: print the exact plan or explicitly apply it
scripts/creator-os reference-refresh --dry-run
scripts/creator-os reference-refresh --apply --source ~/Downloads/tiktok

# Local campaign preparation; never exports and never auto-approves
scripts/creator-os campaign-prepare --confirm-write \
  --folder /path/to/media --campaign campaign_slug --model model_slug

# Free accepted-still fallback
scripts/creator-os static-reel --dry-run \
  --campaign campaign_slug --still /path/to/accepted.png

# Read-only campaign readiness
scripts/creator-os readiness --campaign campaign_slug --user-id user_id

# Draft-only handoff: explicit preview or bounded write; never schedule/publish
scripts/creator-os draft-export --dry-run \
  --campaign campaign_slug --user-id user_id --max-drafts 10

# Metrics/learning sync: explicit preview or apply
scripts/creator-os performance-sync --dry-run

# Paid generation requires confirmation, target, checkout, and finite cap
scripts/creator-os paid-generation --confirm-paid \
  --target Stacey --workspace "$PWD" --campaign campaign_slug \
  --reference-image /path/to/reference.png --max-credits 1
```

Package CLIs remain direct developer implementation boundaries, not generic
operator escape hatches. The supported root surface exposes only the named,
bounded workflows above.

Nothing in this repository command can schedule or publish. Draft export stops
at ThreadsDashboard. Scheduling and publishing are external product actions.

## Contracts

The only hand-edited schema source is:

```text
packages/pipeline_contracts/pipeline_contracts/schemas
```

Generated TypeScript lives at:

```text
packages/pipeline_contracts/typescript/generated-schemas.ts
```

The root `pipeline_contracts/__init__.py` is an active Python import shim, not a
schema mirror. Never hand-edit generated TypeScript.

```bash
pnpm sync:contracts
pnpm check:contracts
```

ThreadsDashboard keeps its own external consumer snapshot. Cross-repository
parity checks are read-only from Creator OS.

## Runtime Truth

The source checkout and runtime checkout are deliberately separate:

```text
/Users/aderdesouza/Developer/creator-os          source integration
/Users/aderdesouza/Developer/creator-os-runtime  pinned machine runtime
/Users/aderdesouza/Developer/ThreadsDashboard    external product source
```

Merging `main` does not promote the runtime checkout. A feature may be locally
implemented, merged, runtime-promoted, or operationally proven; those are four
different claims. `scripts/creator-os status` reports the exact paths and SHAs
it can prove and labels provider/production checks `NOT_RUN` when they were not
performed.

Machine-local credentials, environment files, databases, provider receipts,
runtime logs, and generated media remain outside Git.

## Install And Verify

Requirements are Python 3.11+, a supported Node LTS, pnpm, uv, FFmpeg/FFprobe,
and Tesseract. Optional local model extras are installed separately.

```bash
make install
make reel-models       # optional local placement/identity model bundle

pnpm check:all         # static gates
make test              # all package and integration tests
make verify            # static gates plus all tests
pnpm security:secrets  # local secret scan
```

Package checks remain available for development, for example:

```bash
uv run pytest python_packages/campaign_factory/tests
uv run pytest python_packages/reel_factory/tests
uv run pytest python_packages/reference_factory/tests
pnpm --filter contentforge test
```

Creator OS is proprietary. All rights reserved.

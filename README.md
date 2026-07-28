# Creator OS

Creator OS turns creator intent into postable content batches, sends approved
drafts to ThreadsDashboard, and learns from real performance. It does not own
the product UI, account management, scheduling, or publishing; those belong to
the external ThreadsDashboard repository and
[juno33.com](https://juno33.com).

The durable architecture and runtime map is
[`CREATOR_OS_SYSTEM_MAP.md`](./CREATOR_OS_SYSTEM_MAP.md). Current operational
truth is tracked in [`PIPELINE_STATE.md`](./PIPELINE_STATE.md).

Documentation has three deliberately separate levels:

- `README.md`: supported entrypoints and the shortest accurate introduction;
- `CREATOR_OS_SYSTEM_MAP.md`: durable ownership, dependencies, and failure
  boundaries;
- `PIPELINE_STATE.md` plus dated evidence under `~/.creator-os/analysis/`:
  current source capability and volatile operational proof.

Historical migration plans and snapshots are not runtime instructions.

## Create Content

The normal command names the creator goal, not implementation evidence:

```bash
# Safe plan: resolves approved inventory, prompt, pinned recipe, seeds, and N jobs.
scripts/creator-os create \
  --creator stacey \
  --intent passive_selfie \
  --count 3 \
  --execution cloud \
  --accounts bennett_s33 \
  --audio embedded_trending

# Execute the Higgsfield batch. This still never schedules or publishes.
scripts/creator-os create \
  --creator stacey \
  --intent passive_selfie \
  --count 3 \
  --execution cloud \
  --accounts bennett_s33 \
  --audio embedded_trending \
  --max-credits 100 \
  --apply
```

Production cloud motion uses one pinned, operator-approved Higgsfield recipe:
Kling 3 by default, or Seedance 2 when explicitly configured by the product.
It preserves internal source rotation, Qwen-VL prompt expansion, independent
jobs and receipts, bounded concurrency, native-credit authorization, and exact
output lineage. Provider/model IDs remain internal. There is no WaveSpeed
fallback.

Reference URLs can be downloaded and analyzed without selecting or calling a
provider:

```bash
scripts/creator-os create \
  --creator stacey \
  --intent recreate_reel \
  --reference-url 'https://www.instagram.com/reel/...' \
  --recreate-mode auto \
  --through analyze \
  --audio auto
```

The dry-run uses private temporary media and makes no persistent reference or
audio-library mutation. `--apply --reference-authorized` persists one
deduplicated Reference Factory identity, receipt-linked frame derivatives, an
independently selected scene anchor, and exact reference-audio evidence. It
does not generate, export, schedule, or publish. Instagram, TikTok, YouTube
Shorts, direct HTTP(S) media, and the local-file fallback are supported through
Creator OS's own yt-dlp path; third-party downloader sites are not used.

The existing local-file recreation path remains available:

```bash
scripts/creator-os create \
  --creator stacey \
  --intent recreate_reel \
  --reference-video /private/path/reference.mp4 \
  --reference-platform instagram \
  --reference-authorized \
  --count 1 \
  --execution cloud \
  --accounts bennett_s33 \
  --audio embedded_trending
```

Creator OS analyzes the private reference locally, selects only an approved
same-creator image, and pins Seedance 2 internally. This is broad
structure/performance/camera recreation, not exact choreography. It remains
experimental until an authorized output receives exact-SHA operator approval;
talking references fail closed.

Use `creator-os review` for calibration exceptions, `creator-os export` for the
validated draft boundary, and ThreadsDashboard for account health, scheduling,
publishing, and results. Arena, Router, benchmark evidence, seeds, paths, and
runtime overrides live under developer/research commands and are not normal
operator inputs.

## Product Loop

```text
reference intake
  -> Reference Factory analysis and human labels
  -> reference bank, patterns, prompts, and audio recommendations
  -> Campaign Factory creative plan
  -> Reel Factory generation and lineage
  -> ContentForge headless QC and blocking evidence
  -> Campaign Factory readiness and contract validation
  -> HMAC-signed draft-only handoff
  -> ThreadsDashboard account checks, schedule, and publish
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

The repository deliberately has one owner for each concern: one Campaign
control plane, one Reel media worker, one Reference learning worker, one
ContentForge quality boundary, one canonical schema source, and one external
production publisher. GitHub Actions likewise lives only in the root
`.github/workflows/`; package-local workflow copies are neither supported nor
executed by GitHub in this monorepo.

## Active Creative Path

The normal image path is one reference image through Higgsfield Soul V2 with an
explicit Soul ID. The reference-conditioned result captures the composition
prompt and lineage. An accepted still always receives a local, zero-provider-
cost static MP4. Passive motion uses the pinned Higgsfield Kling 3 or Seedance
2 recipe. Exact-voice talking and motion-copy remain unresolved and fail before
provider submission.

Overlay text always goes through Reel Factory placement and caption rendering.
If no safe lane exists, no overlay is forced. Non-talking motion disables
provider sound; Audio Radar selects a cached live track and Creator OS embeds
and verifies AAC against the exact final MP4 SHA.

Grok, grid/cropped-panel, Qwen, Ollama, Florence, and visual-schema generation
are not Reel Factory operator paths. Their retired execution code and empty
experiment package are removed. The remaining legacy-labelled code is narrow
and caller-proven: XAI anatomy/postability QC, fail-closed compatibility shims,
and read-only historical evidence export.

## One Operator Command

Use `scripts/creator-os` (or `pnpm creator-os -- ...`) for supported operator
workflows:

```bash
# Read-only: repository, contracts, config, runtime, DB, and explicit NOT_RUN checks
scripts/creator-os status

# Networked but zero-product-write/no-generation: HMAC seam + provider probes
scripts/creator-os status --live-read-only

# Read-only fixture-backed integrity audit
scripts/creator-os doctor

# Local reference/audio refresh: print the exact plan or explicitly apply it
scripts/creator-os reference-refresh --dry-run
scripts/creator-os reference-refresh --apply --source ~/Downloads/tiktok

# Library reuse from a local folder; never exports and never auto-approves
scripts/creator-os generate --mode library_reuse --apply \
  --folder /path/to/media --campaign campaign_slug --model model_slug

# Read-only catalog with cost, inputs, outputs, and approval gates
scripts/creator-os generate --list-modes

# Advanced explicit-mode compatibility surface
scripts/creator-os generate --mode soul_static --dry-run \
  --campaign campaign_slug --accepted-still /path/to/accepted.png

# Read-only campaign readiness
scripts/creator-os readiness --campaign campaign_slug --user-id user_id

# Draft-only handoff: explicit preview or bounded write; never schedule/publish
scripts/creator-os draft-export --dry-run \
  --campaign campaign_slug --user-id user_id --max-drafts 10 \
  --surface regular_reel

# Trial Reels are always an explicit, isolated batch and stay fail-closed on
# account OAuth/capability evidence.
scripts/creator-os draft-export --dry-run \
  --campaign campaign_slug --user-id user_id --max-drafts 2 \
  --surface trial_reel

# Metrics/learning sync: explicit preview or apply
scripts/creator-os performance-sync --dry-run

# Advanced paid generation additionally requires confirmation and a spend cap
scripts/creator-os generate --mode soul_static --apply --confirm-paid \
  --target Stacey --workspace "$PWD" --campaign campaign_slug \
  --reference-image /path/to/reference.png --max-credits 2 --wait --download
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

Python imports resolve directly to the uv workspace package. Never add a
root-level import shim and never hand-edit generated TypeScript.

```bash
pnpm sync:contracts
pnpm check:contracts
```

ThreadsDashboard imports the compiled `@creator-os/pipeline-contracts` package
from an immutable, versioned GitHub Release. It does not keep a schema or
TypeScript snapshot. The package URL and npm lockfile integrity pin the exact
consumer artifact; the HMAC handshake negotiates payload schema versions at
runtime.

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

Machine-local credentials and environment files remain under `~/.creator-os/`.
Canonical databases, generated media, models, and logs live under
`~/.creator-os/state`, `artifacts`, `models`, and `logs`; component-specific
variables are explicit rollback overrides. `scripts/creator-os status` reports
these roots, exact source/runtime SHAs, and runtime cleanliness. Add
`--live-read-only` only when configured zero-write seam probes should run.

## Install And Verify

Requirements are Python 3.11+, a supported Node LTS, pnpm, uv, FFmpeg/FFprobe,
and Tesseract. Optional local model extras are installed separately.

```bash
make install
make reel-models       # optional local placement/identity model bundle

make fast              # changed files and focused unit/contract tests
make affected          # canonical PR-development check for affected packages and seams
make release           # broad main/pre-deployment integration verification
make exhaustive        # scheduled deep architecture/security/dead-code checks
pnpm security:secrets  # local secret scan
```

The affected tier avoids rerunning a focused test when the containing package
suite is already selected and prints duration evidence for each command.
Runtime promotion still runs complete verification and 9/9 health; it may skip
only frozen dependency reconstruction when exact dependency inputs, toolchain
identity, and the installed environments all match the prior verified marker.
Missing or changed evidence falls back to the full frozen install.

Package checks remain available for development, for example:

```bash
uv run python -m pytest python_packages/campaign_factory/tests
uv run python -m pytest python_packages/reel_factory/tests
uv run python -m pytest python_packages/reference_factory/tests
pnpm --filter contentforge test
```

Creator OS is proprietary. All rights reserved.

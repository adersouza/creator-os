# Creator OS

**A contract-driven content pipeline for Instagram/Threads creators.**

Creator OS turns reference reels into campaign-ready, audited, dashboard-managed content. The four pipeline tools (`reel_factory`, `campaign_factory`, `contentforge`, `reference_factory`) are source-integrated in this monorepo; ThreadsDashboard remains a separate standalone product repo for juno33.com and is not mirrored here. Production runtime promotion from this repo is explicit, not automatic. Data flows via shared JSON schemas in `packages/pipeline_contracts`.

🔗 **Live Product:** [juno33.com](https://juno33.com)

📋 **Current state ledger:** see [`PIPELINE_STATE.md`](./PIPELINE_STATE.md).

---

## Architecture

```
Reference Media (reels, images, TikTok archives)
        │
        ▼
┌──────────────────┐
│ Reference Factory │  Analyze references, extract patterns,
│     (Python)      │  build learning sets, audio catalog
└────────┬─────────┘
         │  prompt packs, pattern cards, campaign reference bank
         ▼
┌──────────────────┐
│   Reel Factory    │  Direct reference image → Higgsfield Soul ID
│     (Python)      │  → 9:16 still → Kling motion → captions
└────────┬─────────┘
         │  rendered assets + lineage sidecars + audio intent
         ▼
┌──────────────────┐        ┌──────────────────┐
│ Campaign Factory  │───────▶│   ContentForge    │
│     (Python)      │◀───────│   (Node.js)       │
│  Control Brain    │ audit  │  QC / Variants    │
└────────┬─────────┘reports └──────────────────┘
         │  draft payloads (validated by pipeline_contracts)
         ▼
┌──────────────────┐
│ ThreadsDashboard  │  Supabase-backed product app
│  "Juno33"         │  Drafts → Approval → Schedule → Publish
│  (React/TS)       │  Analytics → Performance feedback loop
└──────────────────┘
         │
         ▼
    Performance data flows back to Campaign Factory
    to influence next day's creative plan
```

---

## Repositories

| Repo | Language | Role | Tests |
|------|----------|------|-------|
| [reference_factory](https://github.com/adersouza/reference_factory) | Python | Intelligence — analyze reference media, build learning systems, audio catalog | 69 |
| [reel_factory](https://github.com/adersouza/reel_factory) | Python | Creation — prompt generation, image/video generation, grid crop, caption render | 247 |
| [campaign_factory](https://github.com/adersouza/campaign_factory) | Python | Orchestration — control brain, batch management, audit coordination, draft export | 359 |
| [contentforge](https://github.com/adersouza/contentforge) | JavaScript (Next.js) | Spoofing — FFmpeg variant generation that defeats perceptual-hash duplicate detection (PDQ/SSCD) and rewrites capture metadata so re-used content reads as an original device capture; readiness/forensics checks score how convincing the spoof is | 79 |
| [ThreadsDashboard](https://github.com/adersouza/ThreadsDashboard) | TypeScript | Product — dashboard, scheduling, auto-posting, analytics, multi-account management | 4,557 |
| [pipeline_contracts](https://github.com/adersouza/pipeline_contracts) | Python + TS | Schemas — shared JSON schemas and validators for cross-repo payloads | ✓ |

> **This repo is a source-integrated monorepo.** reference_factory, reel_factory,
> campaign_factory, contentforge, and pipeline_contracts all live here under
> `python_packages/`, `apps/`, and `packages/` (the links above are external
> mirrors). ThreadsDashboard is the one genuinely external dependency.
>
> **In-repo tests: ~1,150 Python (`make test`) + ~130 contentforge JS.** The
> ~4,557 ThreadsDashboard tests run in that separate repo, not here.

---

## How Data Flows

### 1. Reference Intake → Learning System
**Reference Factory** scans local reference media (Instagram reels, TikTok archives), probes video metadata, samples frames, runs OCR, and builds a structured learning corpus. Outputs include:
- Pattern cards with visual format, hook type, and caption archetype labels
- Higgsfield/Kling prompt packs derived from winning patterns
- Audio trend snapshots and recommendations
- A `campaign_reference_bank.json` for Campaign Factory

### 2. Reference Image → Asset Creation
**Reel Factory** now uses the direct reference-image path for active still generation:
- Single-person reference image goes directly to **Higgsfield Soul ID** with `--image`
- Stacey identity is controlled by Soul ID `d63ea9c7-b2c7-439c-bf0c-edfdf9938a36`
- Active stills are `9:16`
- Optional body emphasis is append-only (`none`, `bust`, `bust_hips`)
- **Kling** animates accepted stills into short-form video only when explicitly requested
- Caption variants are rendered with Instagram-style fonts
- Audio intent sidecars are attached (native-audio-first, never burned)

Grok/Qwen/Ollama/Florence visual-schema extraction, grids, cropped panels, and `_grok.json` prompt files are legacy/experimental only.

### 3. Orchestration → Spoof & Verify
**Campaign Factory** acts as the control brain:
- Imports finished videos with full lineage
- Sends them to **ContentForge**, which generates FFmpeg variants engineered to defeat perceptual-hash duplicate detection (PDQ/SSCD) and rewrites capture metadata (`creation_time`, `handler_name`, device-matched x264 params) so re-used content reads as an original device capture
- Two check families: **spoof meters** (`sourceSimilarity`, `variantToVariantSimilarity`, `variationScore`) score how well a variant evades duplicate detection; **quality guards** (`creativeQualityScore`, `readabilityScore`, `safeZoneScore`) enforce a quality floor so spoofing never visibly degrades the output
- Only `overallVerdict: pass` maps to `approved_candidate`; warnings require human review
- Maintains local SQLite campaign database (48 tables), activity logs, and durable job records

### 4. Export → Dashboard → Publishing
Approved assets are exported as draft payloads (validated against `pipeline_contracts` schemas) to **ThreadsDashboard** (Juno33):
- Drafts land in Supabase with `status: 'draft'`
- Native audio safety gates block unsafe audio states from publishing
- Operator approves, schedules, or queues for auto-posting
- Published performance (views, reach, engagement) syncs back to Campaign Factory

### 5. Performance Learning Loop
Campaign Factory ingests posted performance data to influence:
- Pattern ranking and winner selection
- Next-day creative plan generation
- Reference pattern recommendations

---

## Pipeline Contracts

The **single source of truth** for data moving between packages is `packages/pipeline_contracts`. Campaign Factory and legacy root contract folders may keep compatibility mirrors during migration, but those mirrors must be byte-for-byte synchronized with the package source. ThreadsDashboard validates the same contract shape from its external repo, not from a committed Creator OS mirror.

Run the monorepo contract drift check before merging contract or payload work:

```bash
pnpm check:contracts
```

All cross-repo payloads are validated against these schemas:

| Schema | Purpose |
|--------|---------|
| `audio_intent.v1` | Audio metadata attached to rendered assets |
| `audio_catalog_export.v1` | Audio catalog shared from Reference Factory |
| `campaign_draft_payload.v1` | Draft payloads exported to ThreadsDashboard |
| `caption_outcome_context.v1` | Caption performance context for learning |
| `creative_plan.v1` | Daily creative plan structure |
| `generated_asset_lineage.v1` | Full provenance chain for generated assets |
| `higgsfield_soul_image_prompt.v1` | Image prompt format for Higgsfield |
| `kling_3_video_prompt.v1` | Video prompt format for Kling |
| `performance_sync.v1` | Performance data synced from dashboard |
| `pattern_card.v1` | Reusable pattern labels from reference analysis |
| `video_analysis.v1` | Gemini/Grok video analysis output |
| `recommendation_accuracy_report.v1` | Recommendation quality tracking |
| `recommendation_next_batch.v1` | Next batch recommendation payloads |
| `repurposing_plan.v1` | Repurposer plan contract for bounded variant modules |

---

## Boundary Rules

Each repo has strict boundaries documented in [PIPELINE_BOUNDARIES.md](https://github.com/adersouza/reel_factory/blob/main/PIPELINE_BOUNDARIES.md). The critical invariants:

- **Prompt enhancement stays OFF** — Higgsfield does not rewrite prompts
- **Direct reference-image generation is active** — Grok/grid prompt systems are legacy experiments
- **Soul ID owns identity** — reference images guide scene/pose only; do not add identity descriptors into prompts
- **GridCropperV2 seam detection** stays in the crop path
- **Campaign Factory is the control brain** — no other repo makes campaign decisions
- **Native audio first** — trending audio is never burned into generated files
- **No Instagram private API automation** — publishing uses only official approved integrations
- **Draft-first publishing** — nothing auto-publishes without operator approval and safety gates

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| **AI / Generation** | Higgsfield Soul ID, Kling; Grok/Qwen/Ollama/Florence are legacy/experimental unless explicitly requested |
| **Image Generation** | Higgsfield Soul ID (`text2image_soul_v2`) |
| **Video Generation** | Kling 3.0 |
| **Video Processing** | FFmpeg, FFprobe |
| **QC / Similarity** | PDQ, SSCD, SSIM, Chromaprint, Apple Vision OCR |
| **Backend** | Python ≥3.11, Next.js 16 (ContentForge), ThreadsDashboard upstream services |
| **Database** | Supabase (PostgreSQL), SQLite (local Campaign Factory) |
| **Frontend** | React 19, TypeScript, Vite, Tailwind CSS |
| **Deployment** | Creator OS is not the dashboard runtime; ThreadsDashboard owns Vercel/serverless/cron deployment |
| **Payments** | Stripe |
| **Monitoring** | Sentry, PostHog |

---

## Local Development

Each repo is designed to work as a sibling directory:

```
Projects/
├── reference_factory/
├── reel_factory/
├── campaign_factory/
├── contentforge/
├── ThreadsDashboard/
├── pipeline_contracts/
└── creator-os/          ← you are here
```

Campaign Factory uses the Creator OS package paths for pipeline tools. Dashboard integration requires the external ThreadsDashboard checkout at `/Users/aderdesouza/Developer/ThreadsDashboard` or an explicit `THREADSDASH_ROOT`.

Creator OS → ThreadsDashboard draft ingest secret rotation is documented in [docs/runbooks/threadsdash_ingest_secret_rotation.md](./docs/runbooks/threadsdash_ingest_secret_rotation.md).

### Setup, Run, Verify

This is a single `pnpm` + `uv` monorepo (not separate sibling repos). System
prerequisites: `ffmpeg` and `tesseract` (e.g. `brew install ffmpeg tesseract`).

```bash
# 1. Install everything (JS + Python workspaces + git hooks)
make install
#    Note: pulls all extras, including Apple-only reel_factory deps
#    (mlx-whisper, PyGObject). On non-macOS, install without --all-extras.

# 1b. Fetch ignored Reel Factory runtime models for placement + SSCD gates
make reel-models

# 2. Configure
cp .env.example .env   # then fill in Supabase + model keys + secrets

# 3. Run the full stack (contentforge + the 3 Python services)
make dev               # `pnpm dev` alone starts contentforge only

# 4. Verify (mirrors CI: static gates + all test suites)
make verify            # or `pnpm check:all` for static gates only
make test              # tests only (all packages + integration)
```

Per-package tests run directly, e.g.
`uv run pytest python_packages/campaign_factory/tests`.

## Source Integration Status

`creator-os/main` is the CI-green source integration baseline for the pipeline. Large runtime media, model weights, uploads, local databases, and generated artifacts stay outside git. Production deployment routing remains an explicit promotion step; see `AGENTS.md` and `docs/architecture/monorepo_deployment_promotion.md`.

The old phased migration plan is archived at [docs/archive/MONOREPO_MIGRATION_MASTER_PLAN.md](./docs/archive/MONOREPO_MIGRATION_MASTER_PLAN.md) for provenance.

---

## License

Proprietary. All rights reserved.

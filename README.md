# Creator OS

**A contract-driven content pipeline for Instagram/Threads creators.**

Creator OS turns reference reels into campaign-ready, audited, dashboard-managed content through six coordinated local repositories. Each repo owns one concern. Data flows between them via shared JSON schemas defined in `packages/pipeline_contracts`.

🔗 **Live Product:** [juno33.com](https://juno33.com)

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
| [contentforge](https://github.com/adersouza/contentforge) | JavaScript (Next.js) | Quality — FFmpeg variants, similarity/readiness/forensics/compression audits | 79 |
| [ThreadsDashboard](https://github.com/adersouza/ThreadsDashboard) | TypeScript | Product — dashboard, scheduling, auto-posting, analytics, multi-account management | 4,557 |
| [pipeline_contracts](https://github.com/adersouza/pipeline_contracts) | Python + TS | Schemas — shared JSON schemas and validators for cross-repo payloads | ✓ |

**Total verified tests across the pipeline: 5,311+**

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

### 3. Orchestration → Quality Audit
**Campaign Factory** acts as the control brain:
- Imports finished videos with full lineage
- Sends them to **ContentForge** for multi-layer audits (similarity, forensics, compression, provenance, readiness)
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

The **single source of truth** for data moving between packages is `packages/pipeline_contracts`. Dashboard, Campaign Factory, and legacy root contract folders may keep compatibility mirrors during migration, but those mirrors must be byte-for-byte synchronized with the package source.

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
| **Backend** | Python ≥3.11, Next.js 16 (ContentForge), Vercel Serverless (Juno33) |
| **Database** | Supabase (PostgreSQL), SQLite (local Campaign Factory) |
| **Frontend** | React 19, TypeScript, Vite, Tailwind CSS |
| **Deployment** | Vercel (serverless + cron) |
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

Campaign Factory discovers siblings automatically via relative paths (`../reel_factory`, `../contentforge`, etc.) or environment variable overrides.

### Quick Health Check

```bash
# Reference Factory
cd reference_factory && .venv/bin/python -m pytest -q

# Reel Factory
cd reel_factory && .venv/bin/python -m pytest -q tests/

# Campaign Factory
cd campaign_factory && .venv/bin/python -m pytest -q tests/

# ContentForge
cd contentforge && npm test

# ThreadsDashboard
cd ThreadsDashboard && npm test

# Pipeline Contracts
cd pipeline_contracts && python -m pytest -q
```

Use `campaign-factory doctor` for a full cross-repo health check including HTTP service availability.

## Monorepo Migration

`creator-os` is moving toward becoming the unified source-code monorepo for the pipeline, while large runtime media, model weights, uploads, local databases, and generated artifacts stay outside git.

See [MONOREPO_MIGRATION_MASTER_PLAN.md](./MONOREPO_MIGRATION_MASTER_PLAN.md) for the full phased plan, ownership model, test gates, and promotion criteria.

---

## License

Proprietary. All rights reserved.

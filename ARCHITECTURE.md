# Architecture

This document covers the detailed technical architecture of Creator OS.

---

## System Diagram

```mermaid
graph TB
    subgraph Input["Input Layer"]
        IG["Instagram Reels"]
        TT["TikTok Archives"]
        LOCAL["Local Media"]
    end

    subgraph Intelligence["Intelligence Layer"]
        RF["Reference Factory<br/>(Python)"]
        RF_SCAN["Scan / Probe / OCR"]
        RF_LEARN["Pattern Analysis"]
        RF_AUDIO["Audio Catalog"]
        RF_EXPORT["Learning Set Export"]
        RF --> RF_SCAN --> RF_LEARN --> RF_EXPORT
        RF --> RF_AUDIO
    end

    subgraph Creation["Creation Layer"]
        REEL["Reel Factory<br/>(Python)"]
        DIRECT["Direct Reference Image<br/>9:16 Still Path"]
        MOTION["Deterministic<br/>Motion Prompt"]
        HF["Higgsfield Soul ID<br/>Image Generation"]
        KLING["Kling 3.0<br/>Video Animation"]
        CAP["Caption Renderer<br/>IG Fonts"]
        REEL --> DIRECT --> HF --> MOTION --> KLING
        REEL --> CAP
    end

    subgraph Orchestration["Orchestration Layer"]
        CF["Campaign Factory<br/>(Python)"]
        CF_DB["SQLite Campaign DB"]
        CF_IMPORT["Video Import"]
        CF_AUDIT["Audit Coordination"]
        CF_EXPORT["Draft Export"]
        CF --> CF_DB
        CF --> CF_IMPORT --> CF_AUDIT --> CF_EXPORT
    end

    subgraph Quality["Quality Layer"]
        CFG["ContentForge<br/>(Next.js)"]
        FFM["FFmpeg Pipeline"]
        SIM["Similarity Engine<br/>PDQ / SSCD / SSIM"]
        FORENSICS["Forensics /<br/>Compression"]
        READY["Readiness<br/>Summary"]
        CFG --> FFM
        CFG --> SIM
        CFG --> FORENSICS
        CFG --> READY
    end

    subgraph Product["Product Layer"]
        TD["ThreadsDashboard<br/>'Juno33' (React/TS)"]
        SUPA["Supabase<br/>PostgreSQL"]
        AUTO["Auto-Poster<br/>Queue"]
        ANALYTICS["Analytics<br/>Engine"]
        TD --> SUPA
        TD --> AUTO
        TD --> ANALYTICS
    end

    subgraph Contracts["Contract Layer"]
        PC["packages/pipeline_contracts<br/>JSON Schemas"]
    end

    IG --> RF
    TT --> RF
    LOCAL --> RF

    RF_EXPORT -->|"prompt packs<br/>pattern cards<br/>reference bank"| CF
    RF_AUDIO -->|"audio catalog<br/>trend snapshots"| CF

    CF -->|"render requests"| REEL
    CF_AUDIT <-->|"POST /api/similarity<br/>audit reports"| CFG
    CF_EXPORT -->|"draft payloads<br/>validated schemas"| TD
    ANALYTICS -->|"performance sync"| CF

    PC -.->|"validates"| CF_EXPORT
    PC -.->|"validates"| CF_IMPORT
    PC -.->|"validates"| RF_EXPORT
```

---

## Data Flow Detail

### Phase 1: Reference Intelligence

```mermaid
sequenceDiagram
    participant Op as Operator
    participant RF as Reference Factory
    participant Media as Local Media
    participant Gemini as Gemini API
    participant CF as Campaign Factory

    Op->>RF: scan --source ~/Downloads/examples
    RF->>Media: Probe videos, sample frames
    RF->>RF: OCR (Apple Vision → Tesseract fallback)
    RF->>RF: Contact sheets, thumbnails
    Op->>RF: review-server (label gold/maybe/ignore)
    Op->>RF: export-gold
    RF->>Gemini: analyze-reference-with-gemini-api
    RF->>RF: analyze-patterns (heuristic or Ollama)
    RF->>RF: analyze-audio-patterns
    RF->>RF: build-learning-system
    RF-->>CF: campaign_reference_bank.json
    RF-->>CF: higgsfield_prompt_pack.jsonl
    RF-->>CF: audio_patterns.json
```

### Phase 2: Asset Creation

```mermaid
sequenceDiagram
    participant CF as Campaign Factory
    participant RF as Reel Factory
    participant HF as Higgsfield
    participant Kling as Kling 3.0

    CF->>RF: prepare-reel (hooks, recipes)
    RF->>HF: text2image_soul_v2 (Soul ID + reference image, 9:16)
    HF-->>RF: One 9:16 still + captured prompt
    RF->>RF: Human/QC accepts still
    RF->>RF: reel_motion_prompt.py compiles motion prompt
    RF->>Kling: Accepted still as start image + deterministic motion prompt
    Kling-->>RF: Animated short-form video
    RF->>RF: Caption render (IG fonts, timed placement)
    RF->>RF: Audio intent sidecar (native-audio-first)
    RF-->>CF: Rendered assets + lineage + audio intent
```

### Phase 3: Quality Audit

```mermaid
sequenceDiagram
    participant CF as Campaign Factory
    participant CFG as ContentForge
    participant Op as Operator

    CF->>CFG: Stage source in uploads/
    CF->>CFG: Stage rendered asset in output/final/
    CF->>CFG: POST /api/similarity (campaign_factory_v1 profile)
    CFG->>CFG: FFmpeg probe + forensics
    CFG->>CFG: PDQ / SSCD similarity
    CFG->>CFG: Compression review
    CFG->>CFG: Provenance check
    CFG->>CFG: Creative quality heuristic
    CFG-->>CF: Audit report + readiness summary
    alt overallVerdict = pass
        CF->>CF: Mark approved_candidate
    else overallVerdict = warn
        CF->>Op: Human review required
    else overallVerdict = fail
        CF->>CF: Block export
    end
```

### Phase 4: Publishing

```mermaid
sequenceDiagram
    participant CF as Campaign Factory
    participant PC as Pipeline Contracts
    participant TD as ThreadsDashboard
    participant Supa as Supabase
    participant IG as Instagram / Threads

    CF->>PC: Validate draft payload schema
    CF->>TD: export-threadsdash
    TD->>Supa: Upload video to media bucket
    TD->>Supa: Insert media row
    TD->>Supa: Insert post (status: draft)
    Note over TD: Operator reviews draft
    TD->>TD: Native audio safety gate
    alt Audio safe
        TD->>IG: Publish via official API
        IG-->>TD: Post metrics
        TD->>Supa: Store analytics
        TD-->>CF: Performance sync
    else Audio unsafe
        TD->>TD: Block publish, require resolution
    end
```

---

## Database Architecture

### ThreadsDashboard (Supabase / PostgreSQL)
The production database with 472 migrations managing:
- User accounts and team membership
- Connected social accounts (Threads, Instagram, Facebook)
- Posts, drafts, and media storage
- Analytics snapshots and aggregations
- Auto-poster queue and scheduling
- Competitor tracking snapshots
- Social listening alerts
- Stripe billing state
- Webhook event processing

### Campaign Factory (Local SQLite — 48 tables)
A local campaign database with 48 tables tracking:
- Campaign state and metadata
- Source assets and import lineage
- Rendered assets and variant families
- ContentForge audit results
- Account assignments and distribution plans
- Activity logs and durable job records
- Performance sync history
- Caption families and outcome tracking
- Content graph (nodes, edges, sync state)
- Recommendation runs, items, and accuracy
- Trust settings, exceptions, and quarantine
- Audio trend snapshots, selections, and performance rollups

---

## Security Model

### What Creator OS Does NOT Do
- ❌ Instagram/TikTok private API automation
- ❌ Login automation or cookie injection
- ❌ Unauthorized publishing bypass
- ❌ Burn copyrighted trending audio into files
- ❌ Auto-publish without operator approval

### What Creator OS Does
- ✅ Official Meta API integrations only
- ✅ Draft-first publishing with safety gates
- ✅ Native audio resolution (operator attaches in-app)
- ✅ Idempotency guards on all publish paths
- ✅ Kill-switch capability on auto-poster
- ✅ Secrets redacted from job/event metadata
- ✅ Row-Level Security (RLS) on all Supabase tables

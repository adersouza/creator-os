# Creator OS — system map

Measured from the code and the live state stores on 2026-08-07, not transcribed
from the existing docs. Every count in here came from a query or a file walk. Where
this contradicts `CREATOR_OS_SYSTEM_MAP.md` or `PIPELINE_STATE.md`, this document
is the newer measurement; both of those are narrative and drift.

Runtime at time of writing: `48f39cd9` (promoted 2026-08-07T10:08Z from `4869e73f`).

---

## 1. What it is

A headless content factory for Instagram. It ingests reference reels from creators
worth imitating, learns what makes them work, generates original stills and video of
synthetic creators, renders them into captioned reels, gates them behind identity and
quality checks, and hands finished drafts to an external scheduler for a human to
approve and publish.

It never publishes. The last mile is ThreadsDashboard, a separate repo and service.

### State as of today — read this before the rest

The scheduled jobs are green and the code is healthy. **The production pipeline is
idle.**

```
pipeline_jobs       last 2026-08-07   <- this is only the hourly perf sync
source_assets       last 2026-08-06
rendered_assets     last 2026-07-29   9 days
distribution_plans  last 2026-07-21   17 days
```

Nothing has been rendered in 9 days and nothing planned for distribution in 17.
Everything below describes a machine that works; it is not currently being run.
Detail in §13.

## 2. Shape

Two workspaces over one repo.

**Python** (`uv`, members `python_packages/*` + `packages/pipeline_contracts` +
`packages/creator_os_core`):

| package | modules | lines | tests | role |
| --- | ---: | ---: | ---: | --- |
| `campaign_factory` | 233 | 126,296 | 95 | orchestration, state, distribution, provider authorization |
| `reel_factory` | 71 | 30,102 | 48 | rendering: captions, placement, stills, video, QC |
| `reference_factory` | 41 | 22,334 | 12 | ingest and analysis of other creators' reels |
| `creator_os_core` | 20 | 7,742 | — | promotion, config registry, spend, trust boundaries |
| `pipeline_contracts` | 5 | 1,819 | — | 93 JSON schemas + validators |

**JS/TS** (`pnpm`, `apps/*` + `packages/*`): `contentforge` — 55 files, a judge/audit
harness that scores rendered output. It is a consumer of reel_factory, and it
SHA-pins three reel_factory files, so those cannot be edited without breaking it.

`campaign_factory` is 60% of the Python by line count. A test enforces a 1500-line
module cap, which is why so many modules sit at 1,476–1,499 lines and look
arbitrarily split — they are.

## 3. The three factories

### reference_factory — "what works"

Ingests other creators' reels and extracts the reusable parts. Largest modules are
`audio.py` (87K), `patterns.py` (57K), `url_intake.py` (48K), `reference_grok.py`
(44K), `reference_prompt_generation.py` (43K), `reference_analysis.py` (43K).

State (`reference_factory.sqlite`, 45 MB, 29 tables):

```
learning_clusters              2700
frame_samples                  2300
ocr_results                    1850
caption_patterns               1559
source_files                   1394
reference_lifecycle_state       708
video_probes                    577
reference_patterns              577
public_posts                    520
review_labels                   387
audio_catalog                   110
```

It has its own Grok and Gemini adapters, an OCR path, a Swift frame-vision shim,
embeddings, and a 44K-line `server.py` (a FastAPI surface kept for this package
after the general HTTP API was deleted).

### reel_factory — "make the artifact"

Turns a source still or clip plus a caption into a finished 1080×1920 MP4.

```
higgsfield_production.py   2509   the provider client — every paid call
caption_intake.py          1975   harvest -> candidate -> review -> bank
identity_verification.py   1604   ArcFace identity gate
reel_pipeline.py           1197   orchestrator
placement.py               1194   where the caption goes (vision)
reel_pipeline_support.py   1148
observed_profiles.py       1097
generate_assets.py         1088
reel_pipeline_render.py    1042   ffmpeg graph + overlay composite
caption_bank.py             960
derived_stills.py           854
generation_provider.py      698
caption_render.py           642   PIL rasterizer
still_to_reel.py            487   zero-cost still -> MP4
```

Run-root layout: `00_source_videos/ 01_captions/ 02_processed/ 03_audio_library/`.
Note `03_audio_library` is read from the **run root**, not the repo — the repo copy is
empty, and the 41 CC-BY tracks live in `~/.creator-os/artifacts/media/audio_library`.

`manifest.sqlite` (532 KB, 27 tables) is almost empty in production —
`render_attempts 18`, `variations 6`, `winner_dna 5`, `reel_outcomes 1`. The real
production ledger is in campaign_factory; this one is a local render cache.

### campaign_factory — "decide, authorize, account for it"

Orchestration and the system of record. Notable modules:

```
audio_radar/refresh.py              1645   trend discovery
publishability.py                   1499
db_schema.py                        1499
creator_governance.py               1498
adapters/threadsdash_draft_payload  1495
adapters/threadsdash_metrics_ingest 1493
production_higgsfield_authorization 1491   spend gate
recreation_prompting.py             1480
production_lane.py                  1406   creation-mode routing
reel_execution.py                   1341
learning_cohort.py                  1337
```

State (`campaign_factory.sqlite`, 80 MB, 110 tables):

```
content_graph_nodes             5079
artifact_reconciliation_repairs 4486
activity_events                 4480
source_asset_lifecycle_events   3056
content_graph_edges             2390
pipeline_jobs                   1252
source_assets                   1187   quarantined 688 / approved 303 / imported 195
trust_exceptions                 955
generation_output_blobs          777
rendered_assets                  746
generation_attempts              746
render_jobs                      723
quarantined_assets               702
distribution_plans               693
reference_patterns               258
audio_catalog                    197
accounts                         197   all Instagram, all TD-active
```

## 4. Flow

```
  other creators' reels
        |
        v
  reference_factory ── ingest, OCR, probe, cluster, extract patterns
        |                    reference_patterns · caption_patterns · audio_catalog
        v
  campaign_factory ──── plan: pick creator, concept, caption, audio, account
        |                    source_assets -> distribution_plans
        |
        |  authorizes spend, then calls
        v
  reel_factory ─────── anchor (Higgsfield) -> motion (Seedance/Kling) -> caption -> mux
        |                    placement vision · caption_render · ffmpeg
        v
  QC gates ─────────── identity (ArcFace) · anatomy · exposure · placement · similarity
        |
        v
  contentforge ─────── judge / audit the rendered artifact
        |
        v
  approval ─────────── human, per post, immutable v2 approval record
        |
        v
  ThreadsDashboard ─── HMAC-signed draft export; schedules, notifies, reconciles metrics
        |
        v
  performance-sync ─── metrics back into campaign_factory -> learning -> reference_patterns
```

The loop closes: published performance feeds `learning_*` tables, which re-rank
`reference_patterns`, which change what gets planned next.

## 5. Creation modes vs shot modes

Three **creation modes**, frozen, referenced by `pipeline_contracts`,
`campaign_schema_v10`, the recreation identity guards, and the arch-guard test:

- `static_reel` — **free.** `_run_static_reel_batch` (`creation_modes.py:694`) sets
  `provider: None`, `providerQuoteStatus: "not_required"`,
  `quotedProviderCredits: 0`, and only admits assets whose
  `recipe == "static_mp4"` (`creation_modes.py:253`). No provider call.
- `calm_animation` — gentle motion on a still. Paid.
- `recreate_reel` — Seedance 2.0 video-to-video against a reference clip. Paid.

Resolution lives in `production_lane.py:430`: recreate intents → `recreate_reel`,
everything else → `calm_animation`, with `static_reel` allowed for non-recreate.

Corrected 2026-08-07: earlier notes claimed `static_reel` "secretly routes to Kling."
It does not — verified against `creation_modes.py`. There are therefore **three**
zero-cost paths, not one: `static_reel` mode, `still_to_reel.py`, and
`static_mp4.py`.

Five **shot modes** (`docs/operations/reel_shot_modes.md`, authored 2026-08-07) sit
*above* these and carry what the creation mode cannot express — which image model,
whether Motion Control is allowed, which soul, whether captions burn:
`car_talking` · `outfit_spin_jiggle` · `pinterest_calm` · `soul_closeup_bed` ·
`dance_poses`. Specification only; nothing routes on them yet.

Two independent zero-cost paths exist: `still_to_reel.py` (still → MP4, verified
`paidGeneration: false`) and `static_mp4.py`. `static_reel` mode is *not* one of them
despite the name.

## 6. Captions

Pipeline: `external_sources/*.json` → `import-external` → `candidate_intake.json`
→ `swipe-review` → `banks.json`.

```
14 harvest files in external_sources/
1317 candidates pending review
 485 promoted captions across 14 banks
```

Banks: `shared_girl_next_door 157 · experimental_edge 156 · winner_bank 170 ·
comment_bait 92 · boyfriend_bait 80 · coded_fill_ins 48 · body_attention 44 ·
choice_poll 36 · read_backwards_puzzle 32 · goth_dark_alt 19 · dm_follow_bait 17 ·
bedroom_mirror 15 · gym_body 7 · weird_generated_history 0`.

Derived classification (`_content_match_for_review`, computed over all 1317):

```
UNIVERSAL (no scene or context requirement)  1253   95%
CONTEXT-BOUND                                  64
  bedroom 21 · gym 16 · car 6 · outdoor 5 · mirror_selfie 4 · beach 3 · pool 3
  body_forward 12 · action_motion 4 · calm_motion 2 · swim_action 1

delivery:  static_complete 771 · timed_setup_payoff 542 · event_synced 4
```

Two gates remain at intake and both are real: `discoverability_safe_content_contract`
(blocks DM/off-platform language — Instagram shadowban risk) and a 5-char floor.
The word and character caps were intake-only artifacts and were removed 2026-08-07.

### Placement — the part that surprises people

Two systems that do not talk to each other:

- `caption_intake._placement_intent()` stamps every caption with
  `staticBand: "lower_center"`, `creatorStylePreset: "stacey_static_center"`.
  Hardcoded, identical for all 1317.
- `placement.probe_caption_layout(src, duration)` takes **the video only** — the
  caption text is not a parameter. It samples 5 frames, runs YuNet face detection,
  PPHumanSeg person coverage, MediaPipe pose, and per-band luminance/stddev/motion,
  then returns `band ∈ {"top","bottom"}`, style, font, colour. Cached per `src_hash`.

The renderer never reads `placementIntent`. They do not even share a vocabulary —
`"lower_center"` is not in the renderer's value space.

And the vision stack can veto the caption entirely:

```python
placement_allows_overlay = placement_decision.get("status") == "passed"
burn_caption = bool(recipe.burn_caption and placement_allows_overlay)
```

No safe band → the reel renders clean with no overlay and a
`renderPolicy: "clean_without_overlay"` fallback. Silent. This matters most for
`car_talking`, which requires burned captions and is the tightest framing.

Rasterization is PIL (`caption_render.render_caption_png`) composited full-canvas via
ffmpeg `overlay=0:0`. There is no `drawtext` anywhere, so font control is total.

## 7. Audio

Two separate pools.

**Audio Radar** — trend discovery, `audio_catalog` in campaign_factory (197 rows):

```
EVERGREEN 126   (only 2 active)
STALE      42   (0 active, last seen 2026-07-24)
COOLING    20   (20 active)
BREAKOUT    5   (4 active)
HOT         4   (4 active)
                 -> 30 active total
cache: 79 playable objects, 163 MB
```

STALE entries are TikTok "original sound - <account>" scrapes from unrelated niches
(cat videos, Spanish film accounts) that fell off the chart and were auto-deactivated
after 3 consecutive absences. They are not music.

The headline number is misleading: 126 EVERGREEN but **2 active**, so the universal
pool is effectively 2 tracks plus 20 cooling.

**Local royalty-free** — 41 CC-BY tracks in `artifacts/media/audio_library`, each with
`license`, `attribution`, `source_url`, and mood tags. 16× CC-BY-3.0, 25× CC-BY-4.0.

**Intent modes** (`audio_intent.AUDIO_INTENT_MODES`) decide how audio attaches:
`embedded_trending_audio · embedded_original_audio · embedded_creator_voice ·
embedded_royalty_free_audio · native_trending_audio · original_voiceover ·
silent_by_design · platform_auto_music`. Talking reels where Seedance generates the
speech inline are `embedded_original_audio` — nothing to select, nothing to mux.

Refresh: `creator-os audio refresh --region US --max-new N --apply`, weekly launchd
job Monday 04:00. Last successful run 2026-08-03.

## 8. Identity and QC gates

- **ArcFace identity** (`identity_verification.py`, 1604 lines) against
  `identity_reference_set.v4` sets. The sets are **path-bound** — `outputPath` is
  signed into the set, so they cannot be relocated by copying; they must be rebuilt
  with `identity-reference-build`. The gate reads from
  `python_packages/reel_factory/identity_references/`.
- **Anatomy**, **exposure**, **placement**, **similarity** (SSCD), **technical QC**.
- **contentforge** judges the finished artifact separately. Its
  `analyzer-authority.v2.json` pins each analyzer with an
  `approvedImplementationFingerprint`, a `modelFingerprint`, a
  `thresholdsFingerprint` and a `reviewedMaterialFingerprint`. One analyzer is
  `reel_factory.structured_human_media_review`, so changing that reel_factory module
  invalidates its authority record. The fingerprints are **not** raw file sha256s —
  do not try to "fix" a mismatch by pasting `shasum` output; regenerate through
  contentforge.

## 9. Provider surface

All paid generation goes through `higgsfield_production.py` (2509 lines) behind
`production_higgsfield_authorization.py` and `creator_os_core/provider_spend.py`.

Measured costs: Soul 2.0 still ~0.12 credits · Kling O1 image 0.5 · Nano Banana 2k
anchor 2 · Seedance 7 s 480p 10.5 · **refused Seedance ~6** (the quote is refunded, a
separate charge stands) · blocked image job 0.

Two independent NSFW gates — Google/Nano Banana and Seedance — and neither predicts
the other.

Provenance: every provider output carries a Higgsfield `Hf-job-id`; Nano Banana,
Kling, FLUX and Grok ship signed C2PA and SynthID. `normalize_rendered_mp4_metadata`
strips MP4s but **early-returns on non-`.mp4`**, so stills are never normalized. In
practice the still→MP4 path is safe anyway: the ffmpeg re-encode drops the JUMBF box
(measured 2026-08-07: 151 C2PA lines in a source PNG, 0 in the output MP4). Carousels
and stories, which ship stills directly, remain exposed.

## 10. Boundaries

**ThreadsDashboard** — separate repo, 21 adapter modules under
`campaign_factory/adapters/`. Dual HMAC-signed, nonce replay protection,
idempotency keys. Creator OS exports drafts; TD schedules, notifies the operator,
and reconciles published metrics back. 197 Instagram accounts, all TD-active.

**Contracts** — 93 JSON schemas in
`packages/pipeline_contracts/pipeline_contracts/schemas/`, with generated TypeScript
in `packages/pipeline_contracts/typescript/generated-schemas.ts` and `dist/`.
Regenerate with `pnpm sync:contracts`
(`node scripts/generate-pipeline-contract-schemas.mjs`). There is no longer a root
`pipeline_contracts/` mirror directory — older notes that warn about one are stale.

**Runtime promotion** — `creator_os_core/runtime_promotion.py`, 3110 lines, the
largest single module in the repo. Source runs from
`~/Developer/creator-os`; production runs from `~/Developer/creator-os-runtime`.
Promotion requires a signed approval naming 5 specific passing GitHub check runs
(`release`, `Secret scan`, both CodeQL jobs, `Trivy filesystem scan`) bound to the
merge commit, plus a fingerprint over the canonicalized payload, plus a live
`gh api user` identity match, a clean source tree, and an exactly-merged PR. It runs
`make runtime-verify` and a health command, takes a state backup, and rolls back on
failure.

## 11. Scheduled jobs (launchd)

```
threadsdash-performance-sync   hourly
daily-orchestrator             05:45
learning-cohort-daily          08:30
backup                         09:15
ops-digest                     21:30
offsite-backup                 02:15
audio-refresh                  Mon 04:00
weekly-improvement             Sun 21:45
offsite-check                  Sat 03:00
offsite-restore-drill          1st of month 04:00
```

All wrapped by `~/.creator-os/run-job.sh`, which logs to `ops.log` and fires a macOS
banner on failure.

## 12. Disk

`~/.creator-os`, 35 GB after the 2026-08-07 cleanup (was 62 GB).

```
restic-repository   8.7G   local repo restic needs for incremental Supabase upload
library/            8.2G   caption_sources 5.4G
                           higgsfield_full_20260716 1.4G (373 DB-referenced files kept)
                           higgsfield_curated_20260716 1.3G (sha-referenced, 5 hits/file)
artifacts/          6.6G   campaign_factory/campaigns 4.5G (stacey 4.1G)
runs/               3.5G
state/              2.3G
runtimes/           1.9G   ML model venvs, unrelated to the CLI runtime
backups/            1.8G   state-migrations only
analysis/           1.4G
models/             446M
```

`higgsfield_curated_20260716` looks orphaned by a path grep (0 hits) and is not —
its files are referenced by **sha256**, 5 hits each. Any "is this directory dead"
check here must hash, not grep paths.

## 13. Current state — what is actually running

The scheduled jobs are healthy. The **production pipeline is idle**:

```
pipeline_jobs      last 2026-08-07  (this is the hourly perf sync)
source_assets      last 2026-08-06
rendered_assets    last 2026-07-29
distribution_plans last 2026-07-21
```

Nothing has been rendered in 9 days and nothing planned for distribution in 17. Job
history is dominated by `sync_performance` (783 succeeded); actual production is
`run_reel 15`, `prepare_reel 15`, `static_mp4 10`, `motion_generation 3 succeeded /
8 failed`.

The bottleneck is not code. It is that nothing is being kicked off.

## 14. Known open items

- 1317 caption candidates awaiting `swipe-review`. Free, and it gates the bank.
- Shot modes are spec-only; each becomes real on one paid run producing a
  would-post output.
- `placementIntent` is dead metadata — either wire it or delete it.
- `family` in the caption classifier has ~50 values with duplicates
  (`coded_fill_in` vs `coded_fill_ins`, 12 `*_adapted` variants).
- EVERGREEN audio is 126 tracks but 2 active.
- Carousel/story stills bypass provenance stripping.
- `~/Downloads/stacey` — 429 operator-approved generations (106 MP4, 323 PNG) with no
  path into the system. `media intake-existing` explicitly refuses this class.

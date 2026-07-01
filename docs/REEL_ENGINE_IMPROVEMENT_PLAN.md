# Reel Engine Improvement Plan — Codex Master Doc

**Owner:** Emerson. **Author:** Claude (Opus 4.8, 1M). **Date:** 2026-07-01.
**Product:** autonomous/semi-autonomous short-form content engine. Owner supplies REFERENCE
material (competitor/inspiration reels — pose/outfit/scene/hook "winner DNA", NOT identity)
→ system analyzes → generates SIMILAR reels with the owner's trained Higgsfield Soul → QC
(anatomy/exposure/identity/anti-copy) → rank → render captions → schedule to social accounts
via ThreadsDashboard. **Optimize VIEWS + ENGAGEMENT. Bottleneck = content QUALITY + VOLUME.**

## GOAL PROMPT (paste this to Codex to run autonomously to completion)

> **Goal:** implement EVERY item in this document (`docs/REEL_ENGINE_IMPROVEMENT_PLAN.md`), in the
> listed dependency order, one PR each, until the entire Status log at the bottom is checked `[x]`
> and merged. **Do not stop after one item — continue to the next automatically.** You are done only
> when all 17 items are merged green.
>
> **Loop, per item, top-down:**
> 1. Read the item + the Standing Constraints. Implement it on branch `codex/<slug>` as described.
> 2. "Done properly" = ALL per-PR verification passes (`ruff format` + `ruff check`, full `pytest` green,
>    `make verify`, `pnpm security:secrets`, empty `git ls-files models secrets.toml`), the item's own
>    tests are real (not stubbed/skipped), CI is fully green, and the PR is merged. Delete the branch.
> 3. Tick the item's box in the Status log (commit that update), then immediately start the next item.
> 4. Respect the dependency graph — never start an item before its prerequisites are merged (e.g. never
>    ship the bandit 1.5 before 1.2; never do 2.3 before 2.1/2.2).
>
> **Hard rules (never violate, even to "finish"):**
> - Never publish, schedule, post, or run paid/live generation or ThreadsDashboard/Supabase export.
> - Never commit secrets or model binaries; never touch `identity_references/`; never loosen the
>   exposure gate or censor legal-adult captions.
> - Never bypass, weaken, `xfail`, or delete a failing test to make CI green. If a test legitimately
>   fails, fix the code. If the whole suite can't pass, STOP.
> - Never fake completion. A box is `[x]` only when truly merged green with real tests.
>
> **When to STOP and ask the human (do not guess):**
> - An item needs a product decision (identity mapping, which account, thresholds you can't derive).
> - The code is genuinely ambiguous and getting it wrong risks correctness.
> - An item's prerequisite can't be satisfied, or a verification step can't pass after honest effort.
> - You hit anything the Standing Constraints forbid.
> Surface the blocker with specifics and pause; resume the loop once answered.
>
> **Out of scope for you (human action, not a code item):** the learning layers (winner DNA, bandit,
> caption weights) only start producing value once real reels are approved + posted and metrics are
> imported. Build the loop; the human spins the flywheel. Do not attempt to post to generate data.

## How Codex uses this doc

- Work **top-down in the listed order** — items are sequenced by dependency, not just priority.
- **One PR per item.** Branch `codex/<slug>`, one focused commit, open PR, verify CI green, merge, delete branch.
- Re-read the **Standing Constraints** before every item — they apply to all.
- If an item is bigger than expected, ship the smaller correct version and note what's deferred in the PR. Never paper over with a suppression/skip.
- After each merge, update the "Status" checkbox here in a follow-up commit so we can track progress.

## Standing Constraints (apply to EVERY item)

- **NEVER** publish, schedule, or post. **NEVER** run paid or live generation, `--schedule-mode live`,
  `--enable-live`, `--enable-paid-generation`, `export-threadsdash`, or `--allow-unbudgeted-local-test`.
  All work is code + tests only.
- **NEVER** commit secrets (`project_data/secrets.toml`) or model binaries — models are fetched via
  `fetch_models.py` (CI `hygiene` + `secret-scan` block committed runtime-artifact binaries).
- Don't touch `identity_references/` (gitignored face embeddings).
- Exposure ceiling: implied/covered only. Do NOT loosen the exposure gate. Do NOT censor legal-adult
  (18/19) captions.
- Keep `python_packages/reel_factory/tests/fixtures/broad_exception_allowlist.txt` line-synced if any
  `except Exception` handler shifts (`test_exception_boundaries.py` checks exact `file:function:line`).
- Leave the unrelated pre-existing Knip edits (`package.json`, `pnpm-lock.yaml`) untouched.
- **Per-PR verification (all must pass before merge):**
  - `uv run --package reel-factory ruff format python_packages/reel_factory/`
  - `uv run --package reel-factory ruff check python_packages/reel_factory/`
  - `uv run --directory python_packages/reel_factory python -m pytest -q`  (currently **432 passing** as of PR #323 + your new tests)
  - `make verify`
  - `pnpm security:secrets`
  - `git ls-files python_packages/reel_factory/models project_data/secrets.toml`  → must be empty
  - Commit trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

## The core problem (why this order)

The product's thesis is a closed loop: **see what makes a reference win → generate similar →
rank the best → post → measure → feed back**. An audit found the loop broken at every stage:
reference "winner DNA" is fabricated from filenames (never looks at pixels); the generator reads
only subjective taste memory (learned DNA never reaches it); the best-candidate ranker is deleted
(arbitrary reel posts); metrics land in one store while generation is steered by a manual-CSV silo;
the reward signal is raw view-count (learns luck, not engagement); captions are chosen uniform-random;
and the human approve/reject decision is thrown away. **The "smart" layers (bandit, per-soul metrics)
are correct but sit on top of a disconnected loop fed the wrong signal — so the loop fixes come first.**

---

## TIER 0 — Emergency (do first, trivial effort)

### 0.1 Restore the deleted candidate ranker `virality_select.py`  ·  HIGH · S · [x]
**Branch:** `codex/restore-virality-select`
**Why:** the predict-and-select ranker that scores generated candidates and posts the best was dropped
from the tree, but `python_packages/reel_factory/generate_variants.py:18` and `:177` still instruct the
agent to call `virality_select.select_best`. Today an **arbitrary/first** candidate posts — no ranking —
directly bleeding the quality-per-post bottleneck.
**Do:** recover the file + its test from git (it is **not** a rewrite):
```
git show 55fb5925:python_packages/reel_factory/virality_select.py > python_packages/reel_factory/virality_select.py
git show 55fb5925:python_packages/reel_factory/tests/test_virality_select.py > python_packages/reel_factory/tests/test_virality_select.py
```
Re-register in `pyproject.toml` `py-modules`. Reconcile the entrypoint name: docs/AGENTS.md say
`select_best`, the recovered module exposes `rank_candidates` — make them agree (add a `select_best`
alias or fix the references in `generate_variants.py` + `AGENTS.md`). Run its restored test.
**Note:** its reward math must use engagement **rate**, not raw views — if the recovered version uses
raw counts, apply the same fix as item 1.2 here.

---

## TIER 1 — Connect + correct the feedback loop (prerequisite for every smart layer)

### 1.1 Wire winner-DNA / next-batch brief INTO the generator  ·  HIGH · M · [x]
**Branch:** `codex/wire-winnerdna-into-prompts`
**Why:** `generate_prompts.py:1653` injects only `taste_memory(root, campaign)` (subjective operator
lessons). Neither `generate_prompts.py` nor `generate_assets.py` imports `winner_dna` / `next_batch_plan`.
The learned plan is computed then only **printed** by `reel_gui.py` / `next_batch.py`. So "winner DNA →
prompts" does not exist as code.
**Do:** have `generate_prompts.py` accept + merge `next_batch_plan`'s `winner_dna_focus` / `brief` /
`prompt_focus` into prompt construction, via the same seam `taste_memory` already uses. `next_batch`
becomes an input to generation, not a report. Confidence-gate it (respect `data_quality` / `low_data_warning`
already on the plan — don't over-steer on tiny samples).

### 1.2 Fix the reward signal: engagement-RATE, not raw view-count  ·  HIGH · S–M · [x]
**Branch:** `codex/engagement-rate-reward`
**Why:** `intelligence_store.py:299` `winner_score = views + likes*3 + comments*8 + shares*15 + saves*12`,
duplicated in `winner_dna.py:919` and `caption_generation_log.py:271`. With views in the tens of thousands
and engagements in the hundreds, **views dominates** — the whole learned layer optimizes for reach/luck,
not intrinsic quality. This is the wrong objective when the bottleneck is quality.
**Do:** introduce ONE shared scoring helper: blend a **log-scaled reach** term with an **engagement-rate**
term, e.g. `w1*log10(max(views,1)) + w2*((likes + k*comments + j*shares + i*saves)/max(views,1))`. Replace
all three duplicated formulas with it. Keep weights in one constant block. Add a test proving a
high-rate/low-reach reel can outrank a low-rate/viral reel.
**Sequence:** land this **before or with** the bandit (1.5) and before per-soul reporting (2.x) so they
optimize the right objective.

### 1.3 Bridge the two metrics stores (one sync feeds winner DNA)  ·  HIGH · M · [x]
**Branch:** `codex/bridge-metrics-stores`
**Why:** `scripts/sync_threadsdash_performance.py` writes synced metrics into **campaign_factory's** DB,
but `campaign_store.next_batch_plan` reads `reel_outcomes` + `winner_dna` (`campaign_store.py:972-983`),
which are populated **only** by manual `metrics_store.import_outcomes_csv`. The store that steers reel
generation is a hand-fed CSV silo; the two never reconcile.
**Do:** add a bridge step (extend `sync-performance` or a new `refresh-outcomes` command) that writes the
same synced metrics into `reel_outcomes` and calls `refresh_winner_dna`. One sync populates both stores.
No publish/paid actions — read synced data only.
**Status:** Implemented in PR #327.

### 1.4 Write caption `approvedWeights` from outcomes  ·  HIGH · M · [ ]
**Branch:** `codex/caption-weights-from-outcomes`
**Why:** captions are the #1 engagement lever, yet `caption_bank.py:579` `_weighted_bank_item` falls back
to `rng.choice(items)` (uniform random) because **nothing ever writes** `performance.approvedWeights.captionHashes`
(grep finds only readers). Selection is random inside hand-tuned mixes.
**Do:** add a `refresh_caption_weights` job (mirror `refresh_winner_dna`) that joins `reel_outcomes` →
caption_hash (via caption lineage sidecars) and writes `performance.json` `approvedWeights`, so
`_weighted_bank_item` biases toward proven captions. Use the **rate-based** score from 1.2. Depends on 1.3.

### 1.5 Replace next-batch recipe round-robin with an engagement bandit  ·  HIGH · M · [ ]
**Branch:** `codex/campaign-factory-bandit`
**Why:** `campaign_store.next_batch_plan` exploits only — `recipe_hint = best_recipes[idx % len(best_recipes)]`
(campaign_store.py:1012) round-robins the top-3 recipes by mean score. No exploration; a recipe that starts
weak or is new never gets sampled back.
**Do — Thompson sampling, Beta posteriors, posts-as-trials:**
- **Arms** = recipes present in `campaign_outputs` for the campaign ∪ the current default recipe list (new
  recipes stay reachable; do NOT restrict to top-3).
- **Reward per post** = engagement rate `(likes+comments+shares+saves)/max(views,1)`, **clamped [0,1]** (reuse
  the shared helper from 1.2; rate, not raw counts).
- **Posterior per recipe** = `Beta(α,β)`, `α = 1 + Σ rate_i`, `β = 1 + Σ (1−rate_i)` over that recipe's posts
  (effective sample = post count → cold-start explores, converges, never swamped by view volume; zero-post
  recipe = `Beta(1,1)` = explored).
- **Draw:** for each of `count` ideas, sample `θ_r ~ Beta(α_r,β_r)` per arm, pick argmax. Per-idea, so a batch
  mixes exploit + explore.
- Reuse the `campaign_leaderboard` join (`campaign_store.py:893`) to aggregate metrics per recipe. **Stateless**
  recompute each call — no new table.
- **Seedable RNG** param (default `random.Random()`) for deterministic tests. Plain `random` is fine here.
- **Graceful fallback:** zero posts with metrics → fall back to existing round-robin (behavior unchanged with
  no data). Keep `confidence_for_sample_size` / `data_quality` / `low_data_warning`. Add bandit metadata to each
  idea (chosen recipe, its α/β + post count, per-arm sampled θ) for auditability. Bump schema `next_batch.v1 → v2`.
- **Scope:** recipes only. Follow-ups (do NOT build here): 2D recipe×soul bandit; arming winner-DNA feature values.
**Tests:** deterministic w/ seed; cold-start falls back; a batch isn't 100% one recipe (exploration); a clearly
higher-rate recipe wins more across a seed sweep (convergence); rate clamp when engagements>views; zero-view/zero-post
no divide-by-zero.
**Sequence:** after 1.2 (shares the rate reward).

---

## TIER 2 — Make it actually intelligent (feed the loop real signal)

### 2.1 Make reference_factory SEE the pixels  ·  HIGH · M (×parts) · [ ]
**Branch:** `codex/reference-vision-dna`
**Why:** `reference_intake.py:2182` `_pattern_card_from_local` **fabricates** winner DNA: `subjectAction` is the
hardcoded string `"confident selfie-style pose or subtle expression shift"`, `cameraStyle` is fixed, `hookType`
is a filename keyword binary (`:2440`), motion `energy` (`:2421`) and `sceneCuts` (`:2413`) are guessed from
**duration**. Frames ARE extracted (`_extract_reference_frames:2138`, ratios 0.15/0.5/0.85) but only written to
disk, never analyzed. `_visual_format` (`patterns.py:556`) classifies by caption/filename substring, so the
common case (visual-first, no-caption reel) is mislabeled `visual_reference`.
**Do (can split into sub-PRs):**
1. Run a VLM on the already-extracted hook/mid/end frames (local model, or route through the existing
   `Higgsfield video_analysis` / Gemini path) to fill real `subjectAction`, framing, subject count, wardrobe,
   setting, shot list.
2. Replace duration-guessed scene cuts with ffmpeg scene-change detection (`select='gt(scene,...)'`).
3. Classify `visualFormat` from frame embeddings / a small VLM tagger (or nearest-medoid vote over the existing
   DINOv2 clusters) instead of caption keywords.
**Note:** VLM/vision passes may cost tokens — keep them behind the existing analysis flags, no unauthorized paid runs.

### 2.2 Un-silo the real vision path into the production learning join  ·  HIGH · M · [ ]
**Branch:** `codex/unsilo-vision-analyses`
**Why:** `patterns._pattern_source_rows` (`patterns.py:255`) and `learning._pattern_cards` (`learning.py:147`)
join only `public_posts`/`caption_patterns`/`video_probes`/`source_files` — never `reference_video_analyses`
or `viral_pattern_cards`, where the Gemini `recreation_blueprint` + DINOv2 signals land (`_store_pattern_and_analysis:1997`).
So even when an operator runs the good vision analysis, it never reaches the clusters, prompt pack, or
`campaign_reference_bank.json` that Campaign Factory consumes.
**Do:** left-join `viral_pattern_cards` / `reference_video_analyses` into the pattern-card builders; prefer
vision-derived `visualFormat` / `winnerDna` over the text heuristic when present.

### 2.3 Enrich the winnerDNA schema so it can drive generation  ·  HIGH · M · [ ]
**Branch:** `codex/winnerdna-schema-enrich`
**Why:** `patterns.py:764` `_winner_dna` emits only `visualStructure` / `hookType` / `captionArchetype` /
`audioRole`. Prompts are static dict lookups on ~7 enum strings (`_prompt_pattern:685`, `_prompt_template:588`,
`_higgsfield_json_template:617`, `_visual_recipe_hints:479`) → every reel in a bucket yields an identical generic
brief. None of outfit/pose/scene/lighting/subjectCount/framing/motionBeats — exactly what a Soul gen needs.
**Do:** expand winnerDNA to structured per-reference fields (outfit, pose, setting, lighting, framing,
subjectCount, motionBeats, firstFrameGeometry), populate from 2.1's VLM pass, and template prompts from the
per-reference blueprint instead of the shared enum→string tables. Depends on 2.1.

### 2.4 Capture the human approve/reject decision (ContentForge)  ·  HIGH · M · [ ]
**Branch:** `codex/contentforge-capture-decision`
**Why:** `apps/contentforge` `VariationLabPanel.jsx` / `ResultsGrid.jsx` only display + download variants — no
approve/reject/pick control. `app/api/similarity/route.js:449` computes `recommendedAction` but nothing records
whether the human agreed or overrode. The only captured signal (`app/api/audit-feedback/route.js`) logs warning-code
labels into a gitignored test path. The pre-publish gate decision — and the best training signal in the whole
system — is thrown away.
**Do:** capture each review decision (approved/rejected + chosen variant + override-of-recommendation) as durable
structured records, and emit an "approved variants" **manifest** for ThreadsDashboard to consume. **Manifest only —
do NOT publish or schedule** (per AGENTS.md + standing constraints).

---

## TIER 3 — Throughput + hygiene

### 3.1 Per-soul_id metrics attribution (Stacey vs Stacey1 A/B)  ·  HIGH · M · [x] DONE — PR #323 (7d188a02, 432 tests)
**Branch:** `codex/reel-factory-soul-metrics`
**Why:** "Stacey" + "Stacey1" are two Souls (`d63ea9c7`, `5828d958`) split-tested on one brand; metrics
(`publish_metrics`) are keyed filename+account with no soul_id, so you can't tell which Soul wins.
**Do:** add nullable `soul_id` to `publish_metrics` (+ `reel_outcomes`), resolve it **from the source asset lineage**
(not the slot — the slot's soul_id is the campaign identity, which accepts both Souls). Add `soul_metrics_report`
+ `soul-report` CLI aggregating by soul_id with engagement rate; NULL → `unattributed` bucket. Non-blocking:
unresolved → NULL, import still ok.
**VERIFIED resolution chain (Codex's earlier assumptions were wrong — use THIS):**
- Rendered reel `filename` → `<rendered>.mp4.caption_lineage.json` → `captionOutcomeContext.source_clip` = source **stem**
  (top-level `.sourceClip` is often None — read the nested one, or recurse for any non-null `source_clip`).
- source stem → `<root>/00_source_videos/<stem>.*` → load the source asset lineage sidecar → read nested `source.soulId`
  via the recursing `_lineage_value`.
- **TWO source-sidecar names — try BOTH:** `<stem>.generated_asset_lineage.json` (create mode) AND
  `<stem>.direct_reference_lineage.json` (reference-image mode). The default loader only reads the first → would miss
  every reference-image gen.
- Fallbacks: stem-strip `_h\d+_v[^_]+_<color>_<hash>` if caption sidecar missing; then `posting_slots.soul_id`
  (comment: campaign identity, imprecise on shared accounts); then NULL.
**Tests:** resolve through the real chain; BOTH sidecar suffixes (the `direct_reference` case MUST pass); nested
`source.soulId`; missing caption sidecar → stem-strip; unresolvable → NULL/unattributed; report aggregates 2 souls
+ engagement rate. Independent of Tier 1 (can land any order) but more useful after 1.2.

### 3.2 Thin end-to-end orchestrator  ·  HIGH · L · [ ]
**Branch:** `codex/pipeline-orchestrator`
**Why:** no reference→generate→QC→rank→caption→schedule driver exists; every stage is a manual CLI, `Makefile`
only launches dev servers. Throughput is bounded by an operator hand-cranking CLIs — the stated volume bottleneck.
**Do:** add a thin campaign-scoped `reel_factory/pipeline_run.py` chaining `generate_prompts → generate_assets →
QC gates → winner-DNA/virality rank → caption/render → posting_ledger.assign`, with resume/idempotency, driven off
`next_batch`. **STOP before publish** — assignment/draft only. Depends on 0.1 (ranker) + 1.1.

### 3.3 ContentForge Variation Lab → the resumable job queue it already has  ·  HIGH · M · [ ]
**Branch:** `codex/contentforge-lab-jobqueue`
**Why:** `VariationLabPanel.jsx:27` POSTs to the synchronous blocking `/api/variant-pack`; the full `PQueue`-backed
job system in `lib/variant-pack-jobs.js` (idempotency, retries, restart-recovery, poll URLs) is never called. A
timed-out pack or closed tab loses all work. Also `app/api/variant-pack/route.js:35` releases the forge lock on
client abort but never cancels the FFmpeg child → overlapping runs.
**Do:** point the Lab at `startVariantPackJob` + poll `pollUrl`; surface `variantPackJobDiagnostics()`; thread an
`AbortSignal` into `runPipeline`/`runVariantPack` and actually kill the FFmpeg child on abort before releasing the lock.

### 3.4 Unify the split-brain `next_batch` schema  ·  MED · S · [ ]
**Branch:** `codex/unify-nextbatch-schema`
**Why:** `next_batch.py:15-48` prefers `campaign_factory.recommend_next_batch` (`{schema:
"campaign_factory.recommendations.next_batch.v1", items:[...]}`, registered) and falls back to
`campaign_store.next_batch_plan` (`{schema: "campaign_factory.next_batch.v1", ideas:[...]}` — uncontracted, wrong key).
`reel_gui.py:1050,1620` calls the local one directly. Whichever answers governs, and consumers expecting `items`
silently mis-read `ideas`.
**Do:** make the reel_factory fallback conform to `recommendation_next_batch.v1` (emit `items`, registered schema id);
route `reel_gui` through the same `next_batch.py` selection so there's one contract. (Coordinate with 1.5's schema bump.)

### 3.5 Stable join keys instead of filename-suffix matching  ·  MED · S · [ ]
**Branch:** `codex/stable-join-keys`
**Why:** `campaign_store.py:894`, `winner_dna.py:842` + `:922` join metrics↔outputs via
`substr(output_path, ... )=filename`. Renames / cross-dir moves / duplicate basenames silently drop outcomes from
winner DNA + leaderboard — the loop loses data with no error. Stable keys (`job_key`, `asset_generation_id`,
`campaign_output_id`) exist but aren't used.
**Do:** persist the join key at ingest and join on `campaign_output_id` / `job_key` instead of string suffix.

### 3.6 Fix winner-DNA mis-attribution  ·  MED · M · [ ]
**Branch:** `codex/winnerdna-attribution`
**Why:** `winner_dna.py:44` `infer_features_from_text` hardcodes `caption_style="short_direct"` for **every** reel
(`:80`) and only detects `creator="stacey"` (`:78`) — Larissa/Lola always `"unknown"`. `caption_style` can never
learn; per-creator DNA + `best_creator_scene_combinations` are wrong for 2 of 3 creators. Silently poisons briefs.
**Do:** derive `caption_style` from caption lineage / `caption_static_metadata` (length_class/format_class exist in
`caption_bank.py:106`); resolve `creator` from campaign/soul metadata, not substring "stacey".

### 3.7 Smaller quality levers (batch or defer)  ·  MED · S–M · [ ]
- **Rank-weight trending audio:** `audio_provider.py:205` picks `rng.choice` uniformly over top-100 by trend_rank —
  a #1 and #97 sound are equally likely. Weight ∝ 1/rank (or decay); record chosen `track_id` on the outcome so audio
  joins winner DNA. Also caption "quality" (`caption_generation_log.py:27`) is formatting-only and saturates at 100 —
  make the perf term log-scaled + rate-aware (uses 1.2) and add hook/archetype features.
- **Net-new hook generation:** `hook_ai.py:85` runs at `temperature 0.2` with a "preserve meaning exactly" prompt +
  similarity floor — only paraphrases. Add a higher-temp "net-new hook from winning archetype" mode seeded by top
  banks / winner-DNA hook types, keeping the similarity gate only for the rewrite mode.
- **Reference ranking recency/rate:** `public_metrics.py:107` `top_public_posts` orders by raw
  view/play count; `timestamp` (`:71`) stored but unused. Add recency decay + engagement-rate normalization so fresh
  high-rate formats surface and stale mega-viral ones don't dominate the learning set.
- **Transcribe spoken hooks:** no ASR anywhere; spoken/voiceover hooks (a primary retention driver) never captured.
  Add a Whisper pass over reels with audio; extract the first-3s spoken hook into hook/caption archetype classification.

---

## Dependency / sequence summary

```
0.1 restore ranker ─────────────► 3.2 orchestrator
1.2 rate reward ──┬─► 1.4 caption weights ─┐
                  ├─► 1.5 bandit            ├─► (all optimize the right objective)
                  └─► 3.1 soul metrics ─────┘
1.3 bridge stores ─► 1.4 caption weights
1.1 wire DNA→prompts ─────────────► 3.2 orchestrator
2.1 reference vision ─► 2.2 un-silo ─► 2.3 enrich schema ─► (better prompts)
2.4 capture decision (independent)
3.4 schema unify ↔ 1.5 (coordinate schema bump)
```

**Recommended first cut:** 0.1 → 1.2 → (1.1, 1.3, 1.4, 1.5 in parallel-ish) → then Tier 2. Do NOT ship the
bandit (1.5) or soul reporting (3.1) before the rate-reward fix (1.2), or they optimize luck.

## Status log
- [x] 0.1 restore virality_select — PR #324 merged 2026-07-01
- [x] 1.1 wire winner-DNA into prompts — PR #325
- [x] 1.2 engagement-rate reward — PR #326
- [ ] 1.3 bridge metrics stores
- [ ] 1.4 caption approvedWeights
- [ ] 1.5 next-batch bandit
- [ ] 2.1 reference vision DNA
- [ ] 2.2 un-silo vision analyses
- [ ] 2.3 enrich winnerDNA schema
- [ ] 2.4 contentforge capture decision
- [x] 3.1 per-soul metrics — PR #323 merged 2026-07-01
- [ ] 3.2 orchestrator
- [ ] 3.3 contentforge job queue
- [ ] 3.4 unify next_batch schema
- [ ] 3.5 stable join keys
- [ ] 3.6 winner-DNA attribution
- [ ] 3.7 smaller quality levers

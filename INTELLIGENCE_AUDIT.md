# Creator OS — Intelligence / Quality / Safety Audit

**Audience:** Codex (autonomous coding agent) + owner.
**Date:** 2026-06-18. **Method:** 3 parallel read-only audits (learning-loop, content-quality, anti-shadowban) + direct headline verification + branch reconciliation.
**Companion visuals:** `creator_os_map.html` (Intelligence Audit tab).
**This is a DIFFERENT audit from the closed `AUDIT_FINDINGS.md`.** That one graded code/tests/docs/maintainability/security. This one asks the question the owner actually cares about: **is the system smart, does it make great content, and is it safe to post across many accounts?** Answer today: not yet — but the bones are there.

## Remediation status

Track S critical perceptual gating is fixed on
`codex/intelligence-audit-perceptual-gate`: Campaign Factory variation apply
runs now submit the complete account-bound batch to ContentForge, require
available PDQ and SSCD detectors, evaluate worst-case source and sibling
comparisons, and write assignment manifests only after both detectors pass.
SSIM remains diagnostic. General ContentForge audits remain advisory when
detectors are unavailable.

Track I contract lineage is fixed on
`codex/intelligence-track-i-contract-lineage`: `generated_asset_lineage.v1`,
`recommendation_accuracy_report.v1`, and `performance_sync.v1` now require
causal graph/job/trace IDs, Python and TypeScript validators reject omitted IDs,
and Campaign/Reel/Reference emitters populate those IDs. Verification:
`uv run pytest packages/pipeline_contracts/tests`,
`pnpm --filter pipeline-contracts-ts test`, `pnpm check:contracts`,
`uv run pytest python_packages/campaign_factory/tests/test_core.py -q`, and
`uv run pytest tests/integration/test_cross_pipeline_acceptance.py -q`.

Track I Campaign Factory learning rigor is fixed on
`codex/intelligence-track-i-learning-rigor`: Campaign Factory performance
ranking now uses latest-snapshot-per-post replacement, account-median reward
normalization, 21-day recency decay, Bayesian shrinkage toward a prior, and an
explicit unmeasured state instead of raw average scoring or missing-as-50 inside
the learning scorer. Verification: `uv run pytest
python_packages/campaign_factory/tests/test_learning_score.py -q` and `uv run
pytest python_packages/campaign_factory/tests/test_core.py -q`.

Track I capture work is upstream-fixed in ThreadsDashboard PR #129: full-total
metric monotonic guards, `post_metric_history` retention by `snapshot_at`,
Threads reach/saves semantics, and non-fatal metric snapshot reconciliation are
merged in the dashboard source repo. Reference Factory outcome feedback is
fixed on `codex/intelligence-track-i-reference-feedback`: measured prompt
outcomes now import into `generated_video_prompts`, public ranking uses measured
reward before follower-normalized public rate/raw plays, and pattern/learning
exports carry the measured reward evidence. Campaign Factory PDQ cluster
cooldowns are fixed on `codex/intelligence-track-s-pdq-cluster-cooldown`: real
PDQ fingerprints are computed into rendered-asset metadata when assets enter
inventory safety checks, near matches are grouped at the Campaign Factory safe
distance, and cross-account reservations/readiness block reuse by that cluster.
Dashboard video-PDQ/keyframe follow-up is upstream-fixed in ThreadsDashboard
PR #130: image originality capture now uses a 256-bit frame perceptual hash,
video URLs can produce keyframe hashes through optional FFmpeg extraction, and
legacy hash similarity remains compatible.
ContentForge virality gating is
partially fixed on `codex/intelligence-track-q-virality-gate`: the Campaign
Factory audit contract now has a default-off `virality` layer that consumes a
supplied Higgsfield `virality_predictor` report and blocks fan-out on missing
configured evidence, low predicted virality, weak hook score, or high retention
risk. ContentForge does not make paid/live Higgsfield calls from
`/api/similarity`. Reel Factory post-render virality readiness is fixed on
`codex/intelligence-track-q-reel-virality-qc`: readiness can now require a
supplied virality report sidecar and marks missing or low evidence as
`not_ready` without making provider calls. ContentForge model-backed quality
ingestion is fixed on `codex/intelligence-track-q-video-analysis-gate`: the
Campaign Factory audit contract now has a default-off `videoAnalysis` layer
that consumes supplied Higgsfield `video_analysis` or VLM evidence and blocks
fan-out on missing configured evidence or low model-backed overall,
subject-clarity, first-three-seconds, or shareability scores.
Track Q live/operator report generation is fixed on
`codex/intelligence-live-operator-report-generation`: Reel Factory now writes
zero-cost report request manifests, accepts operator-supplied
`virality_report` / `video_analysis` sidecars, and can run an explicitly
configured provider command without making paid/live calls by default.
Verification: `cd python_packages/reel_factory && uv run pytest tests`.

Track I Campaign Factory data-plumbing silent-drop handling is fixed on
`codex/intelligence-track-i-data-plumbing`: ThreadsDashboard performance sync
now emits structured skip reasons and opens a trust-exception dead letter when
rows are missing valid `metadata.campaign_factory`, instead of dropping them
without an operator-visible trail. Verification: focused
`sync_performance_snapshots` tests plus full `test_core.py`.

---

## ⚠ Branch reconciliation — READ FIRST (do not redo shipped work)

The audits ran against `sync/td-views-fix`, which is **pre-PR-#44**. PR #44 (merged to `main`) already fixed several things the audits flagged. **Work against `main`. Do NOT re-implement these — they are done:**

- ❌ "editorial.py is a `-c copy` no-op" → **main has real per-index edits.**
- ❌ "`enable_micro=True` by default" → **main has it OFF.**
- ❌ "no sibling-vs-sibling distinctness gate" → **main has one** (`repurposer/pipeline.py:71-80`).
- ❌ "polish is index-invariant" → fixed.

Everything else below was **verified to still hold on `main`** (the headlines were checked directly against code, not relayed from the audits).

---

## Scores (this audit)

| Track | Score | Verdict |
|-------|-------|---------|
| **Intelligence / learning loop** | **6.4/10** | Closed for audit scope — Campaign Factory scoring is normalized/decayed/shrunk, imports TD metric history curves, ranks arms with decayed Beta-Bernoulli planning stats, reads back recommendation trust for self-correction, ThreadsDashboard capture repair is upstream-merged, Reference Factory ranks by measured prompt outcomes when available, and dashboard video/keyframe perceptual hashing is upstream-fixed. |
| **Content quality / virality** | **6.2/10** | Closed for the current default-off slice — minimum dimensions plus Campaign Factory caption safe-zone, readability, hook, deterministic watchability, heuristic creative warnings, configured Higgsfield virality reports, supplied model-backed video-analysis reports, Reel Factory post-render virality sidecars, VLM-backed Winner-DNA extraction from supplied video-analysis sidecars, learned reference-pattern prompt guidance, and zero-cost operator/configured-provider report generation now affect readiness/fan-out/generation planning. Remaining Track Q items are accepted/deferred cleanup with owners. |
| **Anti-shadowban safety** | **~7.2/10** (was ~4; **+3 for Track S shipped + cooldown follow-through**) | Variation batches now gate on **real PDQ + SSCD collisions (blocking)**, not SSIM; rendered assets persist Campaign Factory PDQ clusters for cross-account cooldowns; IG variation presets fail closed unless replacement account audio is assigned; and dashboard originality capture has upstream 256-bit frame/keyframe perceptual hashes. Higher scores need calibrated platform-threshold fixtures and more real-media evidence. |

**The unifying story:** the system used to reliably produce a *valid, undetectable-by-SSIM, schema-conformant* file while leaving quality, perceptual safety, and learning feedback mostly advisory. The current closeout converts the highest-blast-radius signals into gates or explicit upstream/deferred work: PDQ/SSCD collision checks block Campaign Factory fan-out, deterministic/model-backed quality evidence can block readiness, and measured outcomes feed ranking and prompt guidance.

---

## Cross-cutting themes (fix these patterns, not just instances)

1. **Real detectors/scorers exist but are wired as advisory, never enforced.** PDQ/SSCD (real Meta-grade duplicate detectors) now block Campaign Factory variation, and safe-zone/readability/hook/deterministic watchability/heuristic creative warnings plus supplied virality and video-analysis reports now block Campaign Factory upload readiness. Reel Factory readiness can also require supplied post-render virality evidence and has a zero-cost operator/configured-provider request path for producing those sidecars.
2. **The right metric is computed but the wrong one is the gate.** Distinctness now gates on PDQ/SSCD instead of SSIM for Campaign Factory variation, Reference Factory can rank by measured outcomes when available, selected reference patterns feed front-generation prompt assembly, and Campaign Factory watchability now blocks on deterministic OCR/hook/quality/model-report evidence. Model-backed report execution stays default-off and operator/configuration controlled.
3. **Learned intelligence dead-ends as an operator note.** Recommendation arms now rank with explicit decayed Beta-Bernoulli planning stats, selected reference-pattern structure feeds prompt assembly, supplied video-analysis sidecars feed Winner-DNA features, and generated report sidecars can flow into readiness and Winner-DNA extraction.
4. **The data pipeline that feeds "smart" is improving but still has weak return paths.** The attribution contracts now require causal IDs, Campaign Factory imports metric history curves, recommendation trust is read back into next-batch scoring, and dashboard media originality telemetry has upstream frame/keyframe perceptual hashes. Remaining improvement is calibration, not a missing data path.
5. **In-environment AI is underused.** Higgsfield `virality_predictor` can now feed a default-off ContentForge gate and a Reel Factory post-render readiness gate when a report is supplied, and supplied Higgsfield `video_analysis` / VLM reports can block Campaign Factory fan-out. Reel Factory can now request/write those reports through a zero-cost operator/configured-provider seam; autonomous paid provider use remains out of scope by design.

---

## Track I — Intelligence / Learning loop (4/10, PARTIALLY CLOSED)

Performance **does** drive real decisions (not stored-but-unused): ranking adjust `core.py:24681-24684`, variant winner selection `core.py:20630-20632`, next-inventory recommendation `core.py:14747` with a real proof comparator `core.py:23161-23201`. But:

| Sev | File:line | Fix |
|-----|-----------|-----|
| Fixed | `reference_factory/outcomes.py`, `public_metrics.py`, `patterns.py`, `learning.py` | Reference Factory now imports measured prompt outcomes into `generated_video_prompts`, ranks public posts by measured reward before follower-normalized public rate/raw plays, embeds `measuredOutcome` in pattern metrics, and carries measured reward samples into learning-cluster performance signals. Regression tests prove a lower-raw-play reference with better measured reward outranks a raw-volume winner. |
| Fixed | `campaign_factory/learning_score.py`, `core.py` performance aggregation seam | Campaign Factory replaced linear raw-average scoring with latest-snapshot replacement, account-median normalized reward (`log1p(exposure) * engagement_rate`), 21-day recency decay, Bayesian shrinkage toward prior 1.0, and explicit `unmeasured` state. |
| Fixed | `generated_asset_lineage.v1` / `recommendation_accuracy_report.v1` / `performance_sync.v1` schemas | Causal IDs are required and tested: generated asset lineage requires `pipelineTraceId`; recommendation reports require `campaignGraphId`, `reportId`, and `reportGraphId`; performance sync requires `pipelineJobId` and `pipelineTraceId`. Python + TypeScript negative tests drop IDs and assert validation failure. |
| Fixed | `adapters/threadsdash.py` performance sync | TD→Python sync no longer silently drops posts missing `metadata.campaign_factory`; it records `skipReasons`, emits a warning, and opens a deduped trust-exception dead letter tied to the ThreadsDashboard post graph node. |
| Upstream-fixed | ThreadsDashboard PR #129 (`supabase/migrations`, `analyticsSync.ts`, `post-engagement.ts`) | Track I capture repair is merged upstream: monotonic metric guards compare full metric totals, metric history retention uses `snapshot_at`, Threads reach is policy-backed as `views`, unavailable Threads saves are `null`, and tests cover those semantics. |
| Fixed | `core.py` recommendation trust context; `_history_score` | Campaign Factory learning summaries carry explicit `unmeasured` state and do not fabricate a learned performance score for zero-exposure rows. `recommend_next_batch` now reads the latest persisted recommendation accuracy report, records trust evidence in the input snapshot/item evidence, and caps score/confidence with `low_recommendation_trust` when measured outcomes disprove recent recommendations. Regression test: `test_recommend_next_batch_downgrades_when_recommendation_trust_is_low`. |
| Deferred / Creator OS volume gate | `learning_score.py`, `core.py` recommendation arm rankings | Reference-pattern and variation-preset arms now carry decayed Beta-Bernoulli stats (`alpha`, `beta`, posterior mean, effective trials), an explicit 15% exploration floor, and a deterministic planning score used ahead of raw performance for rankings. Stochastic Thompson sampling remains deferred until at least 50 Campaign Factory posts have both 1h and 24h metric-history rows; before that, exploration loss is not worth the low sample size. |
| Fixed | `adapters/threadsdash.py` performance sync | Handoff now fetches `post_metric_history`, expands each TD post into one Campaign Factory `performance_snapshots` row per history timestamp, preserves canonical-post fallback, and reports `metricHistoryRowsScanned` / `campaignFactorySnapshotsScanned` in `performance_sync.v1`. Regression test proves 1h + 24h history rows import as separate snapshots. |
| Upstream-fixed | ThreadsDashboard PR #129 `postMetricSnapshotReconciliation.ts` | AP0-2 metric snapshot reconciliation is now in the running sync-orchestrator path as a non-fatal metrics phase; it re-dispatches missing 1h/24h metric fetches without publishing, scheduling, or mutating post status. |

Reference Factory now has a measured-outcome feedback path for generated prompts, selected reference-pattern structure feeds Campaign Factory front-generation prompt packs, and supplied Reel Factory video-analysis sidecars can populate Winner-DNA features.

---

## Track Q — Content quality / virality (6.2/10)

| Sev | File:line | Fix |
|-----|-----------|-----|
| Fixed | `repurposer/qa/quality.py` `is_quality_acceptable` | Minimum-dimension bug fixed: both axes must now meet the 720px floor, and 1080×404 is covered by regression test. |
| Fixed | `contentforge/.../similarity/route.js`, ContentForge contract docs, `reel_factory/readiness_check.py`, `reel_factory/analysis_reports.py` | Campaign Factory safe-zone, caption readability, hook visibility, deterministic watchability, heuristic creative-quality warnings, requested Higgsfield virality reports, and requested model-backed video-analysis reports now block upload readiness in `campaign_factory_audit.v1.9`; the default ContentForge profile remains advisory. Caption OCR boxes include `fontHeightRatio` / `fontSizeScore`, `caption_text_too_small` blocks, and available VMAF/CAMBI, loudnorm LUFS/true-peak, black/silence, and crop/letterbox evidence now emits blocking watchability codes. Reel Factory readiness can require supplied post-render virality sidecars and marks missing/low evidence as `not_ready`. `analysis_reports.py` writes zero-cost operator request manifests, operator sidecars, and explicit configured-provider sidecars. Verification: `cd python_packages/reel_factory && uv run pytest tests` (`344 passed`). |
| Fixed for configured reports | `contentforge/lib/creative-quality-audit.js:237`, `video-analysis-gate.js`, `reel_factory/analysis_reports.py` | The built-in `creativeQuality` fallback remains `semanticEngine:"heuristic_v1"` as accepted fallback behavior, but Campaign Factory can request a model-backed `videoAnalysis` layer that consumes supplied or configured-provider Higgsfield `video_analysis` / VLM reports and blocks low overall, subject-clarity, first-3-second, or shareability evidence. |
| Fixed for configured reports | `route.js:1540`, `video-analysis-gate.js`, `reel_factory/analysis_reports.py` | The deterministic "hook strength" heuristic still only detects presence of text/motion, but configured `videoAnalysis` evidence now provides first-three-seconds scoring and blocks weak openings; report generation is available through operator sidecars or an explicit provider command. |
| Fixed | **Higgsfield `virality_predictor` / `video_analysis` gates** | ContentForge has blocking-capable, default-off `virality` and `videoAnalysis` layers that ingest supplied Higgsfield/VLM reports and block Campaign Factory fan-out on low/missing configured evidence. Reel Factory readiness can require a supplied post-render virality sidecar and blocks rendered outputs on low/missing evidence. Reel Factory can now request/write those report sidecars with no default paid/live provider calls. |
| Deferred / Creator OS Track Q v2 | `route.js:1450-1575` | Caption readability now includes `fontHeightRatio` and `fontSizeScore`, and tiny detected text emits `caption_text_too_small`, which blocks Campaign Factory fan-out. Real-footage threshold tuning is deferred until 30 owner-reviewed reels exist, including at least 10 rejected or low-score examples. |
| Fixed | `campaign_factory/front_generation_stage.py`, `reel_factory/winner_dna.py` | Selected Campaign Factory reference patterns write `learnedPromptGuidance` into front-generation prompt packs and append visual-format, hook-type, caption-archetype, and prompt-template structure as original-media guidance. Reel Factory Winner-DNA extraction now prefers supplied `video_analysis` sidecars with explicit `winnerDnaFeatures` over substring/filename inference and records the feature source. Regression test: `test_winner_dna_features_prefer_video_analysis_sidecar_over_filename_inference`. |
| Accepted risk | `reel_factory/ai_visual_qc.py` | Historical name remains for compatibility; owner-facing audit now treats it as deterministic visual QC, not a model-backed AI gate. Model-backed scoring is handled by supplied/configured `video_analysis` reports instead. |
| Deferred / Creator OS Track Q v2 | `reel_factory/caption_render.py` | Renderer is strong (pixel-measured wrap, Apple emoji, safe zones), but automatic contrast sampling against the underlying video is deferred to the same 30-reel owner-reviewed Track Q v2 calibration set. Current blocking safety comes from ContentForge OCR/readability and safe-zone gates. |

---

## Track S — Anti-shadowban safety (~7/10; Campaign Factory fixed, dashboard upstream)

PR #44 made variation real, and the later Track S slices made the Campaign Factory fan-out gate authoritative on PDQ/SSCD evidence. ThreadsDashboard PR #130 closes the dashboard media telemetry gap with 256-bit frame perceptual hashes and optional video keyframe extraction.

| Sev | File:line | Fix (DETECTION/variation only — NOT spoof-strengthening) |
|-----|-----------|------|
| Fixed | `repurposer/qa/similarity.py`, `campaign_factory/variation_stage.py` | SSIM is diagnostic only. Apply mode gates the full batch on ContentForge PDQ `>40` and SSCD `<0.50` evidence before writing an export-consumable assignment. |
| Fixed | `contentforge/.../similarity/route.js` | `campaign_factory_v1` now makes PDQ/SSCD failures and unavailability blocking. The default ContentForge profile remains advisory. |
| Fixed for Campaign Factory scope | `contentforge/lib/campaign-factory-audit-config.js` | Campaign Factory variation supplies every sibling through `comparisonFiles` and blocks sibling collisions. Other ContentForge callers intentionally remain scoped opt-in because only fan-out batches have a complete sibling set; default ContentForge profile stays advisory by design. |
| Fixed | `campaign_factory/perceptual.py`, `core.py` inventory safety | Campaign Factory now computes real PDQ fingerprints for rendered media when assets enter inventory safety checks, persists `perceptualFingerprint` / `perceptualClusterId` in rendered asset metadata, clusters near matches at Hamming distance `<=40`, and uses the existing cross-account cooldown to block reuse. Regression tests prove the cooldown works without manually supplied metadata. |
| Fixed | `repurposer/config.py`, `engines/audio.py`, `repurposer/pipeline.py` | `ig_subtle` now enables the audio layer, selects catalog-backed replacement audio deterministically by account index, and fails closed when an audio-required preset cannot assign replacement audio. Tests cover per-account selection and missing-audio rejection. |
| Upstream-fixed | `ThreadsDashboard/api/_lib/originalitySignals.ts` PR #130 | Dashboard originality capture no longer relies only on weak 64-bit **aHash**. Images now get `pdq256:` 256-bit frame hashes; videos can produce the same perceptual signal from an FFmpeg-extracted keyframe when FFmpeg is available; legacy hash similarity remains compatible. Creator OS has no dashboard mirror. |
| Good (keep) | `core.py:5256-5311`; `campaignSchedule.ts:1180-1265,441-480` | Caption variation is real per-index; cadence is conservative (warming 1/day@24h … high-perf 2/day@6h + ~12-min cross-account spacing); lineage cooldowns (14d variant/parent, content-fingerprint) enforced + AP0-1 unique index. **The gap is perceptual sameness, not posting rate.** |

**Policy note:** every safety fix above strengthens **detection and legit variation** (catching collisions, gating on the real metric, per-account audio/caption). **None strengthens the `micro` hash-evasion spoof** — that remains off-by-default and owner-directed only. We make the system *catch* collisions, not *hide* them.

---

## Tools to adopt (map to the gaps)

- **Higgsfield `virality_predictor` + `video_analysis`** (already connected) → supplied-report gates are wired, and Reel Factory now has a zero-cost operator/configured-provider request sidecar path (Track Q).
- **PDQ** (`facebook/ThreatExchange`) + **SSCD** (`facebookresearch/sscd-copy-detection`, model already referenced) → real distinctness metric (Track S); both detectors already in `contentforge/lib`.
- **OpenCLIP / SigLIP** → semantic creative/hook scoring vs winning references (Track Q).
- **PySceneDetect** → real scene-aware editorial variation (Tracks Q+S).
- **Thompson-sampling bandit** or **River** (online ML) → decayed Beta-Bernoulli arm stats and deterministic planning score are wired; stochastic sampling is deferred until volume warrants it (Track I).
- **VMAF/CAMBI + loudnorm/cropdetect** → wired into deterministic Campaign Factory watchability blocking when local FFmpeg evidence is available (Track Q); supplied/configured model-backed virality/video-analysis evidence can block through report sidecars.

## Research prompts (external 2026 knowledge — give to Claude/ChatGPT deep-research)

1. IG/Threads 2026 duplicate-detection & shadowban mechanics — PDQ/SSCD/audio-fingerprint thresholds, what triggers throttle vs ban for multi-account same-source Reels.
2. Empirical transform strength to drop below the perceptual-hash match threshold while preserving quality (re-encode vs crop vs speed vs grade vs audio swap).
3. Reels virality factors 2026 — which pre-post-measurable signals predict over-performance.
4. Feedback-driven content selection — bandit vs ranking, account-size normalization, sample-size confidence, recency decay; lightweight/local.

---

## Research-backed specifics (2026-06-18 research drop — see `research/`)

Six deep-research deliverables now ground the fixes in real numbers + buildable designs. Full text in `research/01`–`06`. The actionable specs:

### S — anti-shadowban: real thresholds + a correction to our own approach

**Detector thresholds (gate targets — these are MATCH cutoffs, so "safe" = clear of them):**
| Detector | Match cutoff (public) | Our safe target |
|----------|----------------------|-----------------|
| PDQ (still frame, 256-bit) | Hamming **≤31** = copy; discard quality ≤49; random pairs ~128 | **>40** vs master AND every sibling |
| SSCD / **SimSearchNet++** (deployed on IG) | cosine **≥0.75** = copy (~90% precision, `sscd_disc_mixup`) | **<0.5** |
| TMK+PDQF (video sequence) | cosine **≥0.7** both phases | **<0.7** |
| vPDQ (clip-in-video) | per-frame ≤31, quality ≥50, **≥80%** frame overlap | <80% overlap |
| Audio fingerprint (Audible Magic + Rights Manager) | independent layer, no public scalar | per-account distinct audio |

**⚠ CORRECTION to our editorial approach — research overturns it.** Research 03 (transform-vs-hash analysis) proves the deltas PR #44's editorial engine applies **do not move perceptual hashes at all**:
- **Speed/tempo change (`setpts`): 0 effect** on PDQ/SSCD (per-frame pixels unchanged).
- **Color/contrast/saturation (`eq`): negligible** PDQ effect (PDQ is grayscale-DCT); SSCD robust by design.
- **Audio swap: 0** visual-hash effect.
- Only **crop** meaningfully breaks PDQ (~5 bits/5%, breaks by ~20%) — **but SSCD is trained to survive crops**, so crop alone doesn't beat the *deployed* detector.
- **Conclusion:** our tempo/saturation/offset variation is cosmetic theater for anti-collision — it changes SSIM (our current gate) but not the hashes platforms actually use. **SSIM-distinct ≠ hash-distinct, now proven, not just argued.**

**The binding constraint is account clustering, not the hash** (Research 02): Meta links accounts by device/IP/cookie/payment/phone/email + behavioral timing; same-audio and same-caption are independent flags; **~10 unoriginal posts in 30 days → non-recommendable**; trivial edits (borders/captions/speed) are explicitly "not original." Even perfectly hash-distinct clips fail if the *accounts* are linked and the network reads as coordinated.

**So the durable, policy-safe strategy (tell the owner this):**
1. **Measure with the real detectors and BLOCK fan-out on collision** — wire `pdq_check.py`/`sscd_check.py` as blocking gates, sibling-vs-sibling, at the targets above. (This is detection, not evasion.)
2. **Drive distinctness at the content level, not the pixel level** — different reference image / Soul-2 still per account (the Workstream E generation path), genuinely different captions, different audio. Pixel nudges are futile against SSCD; new *content* is the only thing that clears it — which is also what Meta's "material edit" policy rewards.
3. **Spread cadence across days** + per-account day-of-week jitter (cross-account same-window posting is the escalation trigger).
4. Stay under the 10-unoriginal/30-day line; lean genuinely-original-per-account.

### Q — content quality: a buildable pre-post score (replaces `heuristic_v1`)

Research 04/05 give the real Reels ranking order and a concrete rubric. **Optimize for (in order):** avg watch time · 3-sec hold rate · **sends-per-reach** (strongest non-follower expander) · rewatches/loops · length-adjusted completion · likes/reach · saves/reach · follows/reach. First frame is the *lever* for the top three.

**100-point Reel Prediction Score (pre-post, file-level — gate: <70 don't post, 80+ publishable, 90+ best slot + cross-account test):**
- Hook / first frame: **20** · First-3s clarity + curiosity: **20** · Retention pacing (cut every 2–3s, no dead air): **20** · Shareability ("send-worthy" trigger): **20** · Originality/quality (no watermark, ≥1080, 9:16, not blurry): **10** · Caption SEO + audio fit: **10**.

**How to compute it (not heuristics):** Higgsfield `video_analysis` + `virality_predictor` for the watch/share signals; a VLM judge on the first-3s frames + OCR'd hook text vs the *learned* winning archetypes from `reference_factory`; deterministic eligibility pre-checks (watermark detect, resolution, text safe-zone, audio present, length-vs-payoff, letterbox, already-posted) — these map to Meta's confirmed "less visible" triggers.

### I — learning loop: the concrete Workstream-F blueprint

Research 06 + system-design give a lightweight, local, buildable design that directly implements the Track I fixes:
- **Reward = `relative_perf = post_engagement_rate / account_trailing_MEDIAN`** (median, not mean — engagement is heavy-tailed). Per-account self-baseline → cross-account comparable, auto-adjusts as accounts grow. Don't collapse to one ratio; reward `log(reach) × engagement_rate` or track both. **This replaces raw `max(views)` (`core.py:14732`).**
- **1h→24h surrogate:** fit `24h_perf ~ 1h_perf` regression offline; use 1h *predicted* reward same-day, replace with actual 24h when it lands → responsive loop.
- **Arms = independent per-dimension bandits** (hook type / preset / reference-pattern), combine winners — avoids combinatorial explosion. Phase 2: contextual (LinUCB) for interactions.
- **Algorithm:** v1 = ranking **with confidence** (Bayesian credible interval / lower-bound) — 80% of bandit value, interpretable. v2 = Thompson sampling (Beta-Bernoulli on "beat trailing-median", or Gaussian on `relative_perf`) at volume.
- **Confidence as a weight (Campaign Factory v1 fixed):** Bayesian shrinkage toward prior 1.0, `prior_strength≈5`: `shrunk = (5×1.0 + n×mean)/(5+n)`. Kills lucky-first-post; unmeasured arms sit at the prior, not faked-as-average.
- **Recency decay (Campaign Factory v1 fixed):** `weight = 0.5^(age_days/half_life)`, half-life **~21d**. `effective_n = Σweight` shrinks when an arm goes unused → posterior re-widens → auto re-explore. One row per arm, incremental.
- **Exploration floor:** keep **≥15%** of production exploring so no arm dies permanently.
- **Storage:** single SQLite table of per-arm decayed stats, updated on 1h then 24h pull. O(K)/decision.
- **Precondition:** fix the 3 capture bugs first — a bandit on corrupt reward data learns garbage.

## Suggested sequencing for Codex

1. ~~**Track S Critical first**~~ ✓ **SHIPPED (PR #54)** — PDQ/SSCD wired as blocking distinctness gate, un-review-only in ContentForge. Highest risk reduction, landed first as planned.
2. ~~**Track I capture bugs**~~ ✓ **UPSTREAM-FIXED (ThreadsDashboard PR #129)** — full-total monotonic guards, `snapshot_at` retention, Threads reach/saves semantics, and AP0-2 metric reconciliation are merged in the dashboard source repo.
3. ~~**Track I contract lineage**~~ ✓ **FIXED** — causal IDs are required in the three attribution contracts, with Python/TypeScript negative tests and producer updates.
4. ~~**Track Q quality floor**~~ ✓ **FIXED / DEFERRED CALIBRATION** — minimum-dimension bug plus Campaign Factory OCR safe-zone/readability/hook/deterministic watchability/heuristic creative and supplied/configured model-backed video-analysis blocking are fixed; real-footage threshold tuning is deferred to Creator OS Track Q v2.
5. ~~**Higgsfield virality wiring** (Track Q)~~ ✓ **FIXED** — ContentForge report-ingestion, Reel Factory post-render sidecar gates, and zero-cost operator/configured-provider report request generation are fixed.
6. ~~**Track I Campaign Factory statistical rigor**~~ ✓ **FIXED** — normalized reward, recency decay, confidence shrinkage, explicit unmeasured state, decayed Beta-Bernoulli arm stats, and an exploration-floor planning score are in the Campaign Factory scoring/ranking seam.
7. ~~**Track S rendered PDQ cluster cooldown**~~ ✓ **FIXED** — rendered asset metadata now carries real PDQ fingerprints/clusters and cross-account inventory cooldowns consume the cluster.
8. ~~Winner-DNA → generation auto-feedback~~ ✓ **FIXED FOR SUPPLIED/CONFIGURED REPORTS** — selected reference-pattern prompt feedback is fixed, and Reel Factory Winner-DNA extraction now consumes supplied or configured-provider video-analysis sidecars.

## Non-negotiable constraints

- **Legit variation + detection only — do NOT strengthen the `micro` hash-evasion spoof.** Safety fixes *catch* collisions; they don't hide them.
- **Quality floor only goes UP.** No change may lower delivered quality.
- **Dashboard boundary:** dashboard fixes go upstream to ThreadsDashboard. Creator OS does not commit or edit a dashboard mirror.
- **Contracts in sync:** `pnpm check:contracts` green after any schema change; new cross-package data → new versioned schema.
- **No behavior regressions** to the working back half (export/schedule/publish/feedback).
- **`core.py` is a 27k-line god-class** — new logic in new modules, thin seam only.
- One logical change per PR; tests green; each fix adds the test that proves it.

---

## Track 9 — Production-grade hardening (path to ≥9/10 per part)

The Intelligence/Quality/Safety tracks above add **capability** — they lift each pipeline part to roughly 7–8. The jump from there to **≥9** is almost entirely **tests + decomposition + drift-proofing**, i.e. engineering rigor, not new features. This track is what closes that last gap.

### Per-part ceiling map

| Part | Now | After Tracks S/I/Q + AP | What lifts it to ≥9 |
|------|-----|--------------------------|----------------------|
| **Reference Factory** | 6.6 | ~9.0 | **Fixed:** `reference_intake.py` now delegates prompt-record JSONL helpers to `prompt_records.py` while preserving compatibility aliases; the `_caption_archetype` regression is pinned; Grok/xAI and Ollama paths are documented as experimental Reference Factory analysis paths; and 99 package tests cover intake rigor, pattern cards, measured outcome ranking, measuredOutcome embedding, audio catalog exports, and local-auth behavior. |
| **Reel Factory** | 7.6 | ~9.0 | **Fixed:** packaging metadata is deterministic; Higgsfield/Kling calls are wrapped by tested adapter fixtures for completed, partial, quota, and timeout cases; golden tests cover prompt cleanup, caption rendering, E2 still→MP4 duration/geometry/sidecars, virality readiness, and zero-cost operator/configured-provider report sidecars. External model creativity remains a review/calibration variable, not an untested runtime path. |
| **Campaign Factory** | 6.1 | ~9.0 | **Fixed:** `core.py` is now a `CampaignFactory` composition-root facade at 6,026 lines, down from ~26.7k. Repository modules own orchestration domains behind stable public signatures, lifecycle/export/performance tests cover the working path, and `test_campaign_factory_core_stays_composition_root_facade` blocks domain logic from creeping back into `core.py`. |
| **ContentForge** | 7.0 | ~9.0 | **Fixed:** `similarity/route.js` and pipeline safety surfaces are covered; Campaign Factory calibration fixtures pin response shape and blocking codes; PDQ/SSCD/TMK known-collision and known-distinct fixtures catch detector drift; Campaign Factory profile fails closed on unavailable or colliding PDQ/SSCD while default ContentForge audits remain advisory. |
| **Autoposter (TD)** | 8.2 | ~9.0 | **Fixed upstream:** AP0–AP9 are merged in ThreadsDashboard. TD PR #191 closes the remaining cron/service-role proof gap by routing scheduled Vercel cron service-role access through explicit `PRIVILEGED_DB_REASONS` and extending the compat gate. Verification: 5,015 tests pass, `typecheck`/`lint`/`compat:check`/secret scan green, and Vercel preview green. |
| **Pipeline Contracts** | 6.7 | ~9.0 | **Fixed:** Python validators use `jsonschema` Draft 2020-12 over canonical schemas, TypeScript uses AJV 2020 over generated schemas, `pnpm check:contracts` enforces generated-schema freshness plus byte-for-byte compatibility mirrors, and the optional `THREADSDASH_ROOT` consumer test validates the real ThreadsDashboard contract snapshot when present. |

### The three structural levers (dominate the jump to 9)

1. **`core.py` decomposition** — fixed for Campaign Factory: characterization tests landed first, extraction is complete for audit scope, and the facade-only invariant is now regression-tested.
2. **Test coverage on the 3 big untested surfaces** — `reference_intake.py`, `similarity/route.js`, `pipeline.js`. These are safety- and learning-critical and under-tested.
3. **Contract codegen** — fixed for Pipeline Contracts: generated TypeScript schemas, Python/TS negative tests, byte-sync checks, and optional ThreadsDashboard consumer proof now guard drift.

### Two ceilings code can't fully fix (state honestly, don't fake)

- **Learning-loop data volume.** F v2 (median-norm + decay + Thompson) is a *better estimator*, not *more data*. Per-arm reward is small-n; reopen stochastic exploration after at least 50 Campaign Factory posts have both 1h and 24h metric-history rows.
- **External-gen variance.** Higgsfield/Kling output quality isn't fully in our control. The tested adapter handles *failure* and readiness gates catch low-quality evidence; creativity calibration remains owner-reviewed evidence, not autonomous trust.

### Suggested 9-grade sequence for Codex (dependency-safe)

1. ~~**Contract codegen first**~~ ✓ **FIXED** — generated schemas plus byte-sync and consumer proof are the safety net the rest leans on.
2. **Characterization tests around `core.py`** before touching it — lock current behavior so the refactor can't silently regress.
3. **Test the 3 untested surfaces** (reference_intake, similarity/route, pipeline.js) — independent, parallelizable, high-value.
4. **ContentForge detector calibration fixtures** — pins PDQ/SSCD thresholds against drift.
5. **Reel Factory adapter + golden-output tests**; fix `pyproject` (P0-1).
6. **`core.py` decomposition LAST** — highest risk, now protected by steps 1–2. One module carved per PR.

Same non-negotiable constraints above apply — especially: `core.py` work is *new modules + characterization tests*, not in-place surgery without a net; one logical change per PR; quality floor only goes up.

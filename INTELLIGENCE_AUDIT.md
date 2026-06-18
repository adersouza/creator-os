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

Track I capture work, Reference Factory outcome feedback/statistical rigor,
Track Q quality/virality work, perceptual cooldowns, per-account audio, and
upstream ThreadsDashboard work remain open.

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
| **Intelligence / learning loop** | **5/10** | Partially closed — Campaign Factory scoring is normalized/decayed/shrunk, but the loop is still human-gated and leaks at capture, Reference Factory feedback, and dashboard boundaries. |
| **Content quality / virality** | **3.5/10** | Partially closed — minimum dimensions and Campaign Factory caption safe-zone overlap now block, but watchability, readability, model-backed creative scoring, and virality gates remain open. |
| **Anti-shadowban safety** | **~6.5/10** (was ~4; **+2 for Track S shipped, PR #54**) | Variation batches now gate on **real PDQ + SSCD collisions (blocking)**, not SSIM, and IG variation presets fail closed unless replacement account audio is assigned. Remaining gap to higher: rendered PDQ cluster cooldowns + dashboard aHash/video PDQ upstream work. |

**The unifying story:** the system reliably produces a *valid, undetectable-by-SSIM, schema-conformant* file — and does almost nothing to ensure it's **good**, that it **won't hash-collide across accounts**, or that what it learned **changes what it makes next**. Three different audits, one root pattern: **real signals exist but are computed-and-ignored.**

---

## Cross-cutting themes (fix these patterns, not just instances)

1. **Real detectors/scorers exist but are wired as advisory, never enforced.** PDQ/SSCD (real Meta-grade duplicate detectors) now block Campaign Factory variation, and safe-zone overlap now blocks Campaign Factory upload readiness. VMAF/CAMBI quality machinery, readability, creative, and virality scoring are still unused or advisory. The fix is often *wiring*, not *building*.
2. **The right metric is computed but the wrong one is the gate.** Distinctness gates on SSIM (structural) instead of PDQ/SSCD (perceptual-hash). Quality gates on resolution instead of watchability. Campaign Factory learning now uses normalized, recency-decayed, confidence-weighted scoring; Reference Factory ranking and quality/virality gates still need the same treatment.
3. **Learned intelligence dead-ends as an operator note.** Winner-DNA, recommendation trust score, creative recommendations — all computed, none auto-fed back into generation or ranking.
4. **The data pipeline that feeds "smart" leaks at the contract boundary.** The internal SQLite carries full lineage (post_id/variant_id/concept_id/...); the *exported contracts* drop those IDs, so Workstream F cannot attribute performance to cause even though the data exists.
5. **In-environment AI is unused.** Higgsfield `virality_predictor` + `video_analysis` are available (skill + `video_analysis.v1` contract scaffold) and wired into no gate or scoring decision.

---

## Track I — Intelligence / Learning loop (4/10, PARTIALLY CLOSED)

Performance **does** drive real decisions (not stored-but-unused): ranking adjust `core.py:24681-24684`, variant winner selection `core.py:20630-20632`, next-inventory recommendation `core.py:14747` with a real proof comparator `core.py:23161-23201`. But:

| Sev | File:line | Fix |
|-----|-----------|-----|
| High | `reference_factory/patterns.py:569-603`, `public_metrics.py:99-116` | Ranking is raw-count: `log10(plays)` on absolute competitor plays, clusters by `sum(plays)`. **No account-size normalization** → big accounts always win. Divide by follower count. |
| Fixed | `campaign_factory/learning_score.py`, `core.py` performance aggregation seam | Campaign Factory replaced linear raw-average scoring with latest-snapshot replacement, account-median normalized reward (`log1p(exposure) * engagement_rate`), 21-day recency decay, Bayesian shrinkage toward prior 1.0, and explicit `unmeasured` state. |
| Fixed | `generated_asset_lineage.v1` / `recommendation_accuracy_report.v1` / `performance_sync.v1` schemas | Causal IDs are required and tested: generated asset lineage requires `pipelineTraceId`; recommendation reports require `campaignGraphId`, `reportId`, and `reportGraphId`; performance sync requires `pipelineJobId` and `pipelineTraceId`. Python + TypeScript negative tests drop IDs and assert validation failure. |
| Fixed | `adapters/threadsdash.py` performance sync | TD→Python sync no longer silently drops posts missing `metadata.campaign_factory`; it records `skipReasons`, emits a warning, and opens a deduped trust-exception dead letter tied to the ThreadsDashboard post graph node. |
| High (capture bugs — corrupt training data at source) | `supabase/migrations/20260307210000_monotonic_metric_updates.sql:36-41` · `analyticsSync.ts:716` · `post-engagement.ts:130-142` | (a) monotonic guard compares views-inclusive vs views-exclusive → per-post 24h UPDATE no-ops; (b) 90-day retention `delete().lt("created_at",…)` but column is `snapshot_at` → errors every run, swallowed, table grows unbounded; (c) Threads `reach`/`saves` never written (always 0) but the score weights them. |
| Partial | `core.py:23197` trust score; `_history_score` | Campaign Factory learning summaries now carry explicit `unmeasured` state and do not fabricate a learned performance score for zero-exposure rows. Trust score self-correction is still not read back. |
| Med | `adapters/threadsdash.py:3004` | Handoff reads canonical `posts` row only, never `post_metric_history` time-series → F sees one point, no velocity/retention curve. Pull the time-series. |
| Med | AP0-2 `postMetricSnapshotReconciliation.ts` | AP0-2 reconciliation is real but lives only in TD's `audit/analytics-view-coverage` branch — **port it into the running path**; it doesn't touch the 3 capture bugs above. |

**reference_factory has NO feedback loop at all** (one-directional: scrape→score→emit). Add outcome columns to `generated_video_prompts` (`db.py:296`) so it ranks patterns by *our* measured results, not competitor leaderboard order. (On its own it scores ~2/10.)

---

## Track Q — Content quality / virality (3/10)

| Sev | File:line | Fix |
|-----|-----------|-----|
| Fixed / Critical remainder | `repurposer/qa/quality.py` `is_quality_acceptable` | Minimum-dimension bug fixed: both axes must now meet the 720px floor, and 1080×404 is covered by regression test. Remaining Track Q work: add a real watchability floor for compression, audio loudness (LUFS), VMAF/CAMBI banding (**machinery already exists** in `contentforge/lib/quality-metrics.js` — `runVmaf`/`cambi`, unused), framing/motion/legibility, and subject-crop checks. |
| Fixed / Critical remainder | `contentforge/.../similarity/route.js`, ContentForge README/contract docs | Campaign Factory safe-zone overlap warnings now block upload readiness in `campaign_factory_audit.v1.5`, with default profile still advisory and docs corrected. Remaining: `creativeQuality`/`readability`/`hookVisibility` are still advisory-only, and model-backed quality/virality gates remain open. |
| Critical | `contentforge/lib/creative-quality-audit.js:237` | Self-labeled `semanticEngine:"heuristic_v1"`, `modelBacked:false`. Hook scoring = keyword bag-matching. Replace with an LLM/VLM judge (or Higgsfield `video_analysis`) scoring the first-3s frames + OCR'd hook against learned winning archetypes. |
| High | `route.js:1540` | "Hook strength" = `earlyTextBoxes>0 ? 100 : avgDelta>=10 ? 60 : 20` — only detects presence of text/motion, can't tell good from bad. |
| High | **Higgsfield `virality_predictor` unused** | Plug it in at two points: (a) contentforge as a new **blocking-capable** `virality` layer; (b) reel_factory post-render QC so low-predicted-virality clips are auto-rejected/down-ranked **before** posting. Converts "is it postable" → "will it perform." Lowest-effort high-leverage win. |
| Med | `route.js:1395` | Real per-box `readabilityScore = confidence*0.7 + contrast*0.3` measures OCR *detectability*, not legibility at distance — no font-height÷frame-height term, so tiny-but-crisp text scores "readable." Add the ratio. |
| Med | `reel_factory/winner_dna.py:30-45`, `campaign_store.py:799-806` | Winner-DNA = substring keyword matching; `prompt_focus` is a 5-value enum dead-ending as an operator note. Feed winning scene/pose/motion/caption-archetype directly into the prompt-assembly step; upgrade feature extraction to VLM on the actual winning videos. |
| Med | `reel_factory/ai_visual_qc.py` | Named "AI visual QC", contains no model (OpenCV blur/jump thresholds). Either add a model or rename; today it's a heuristic. |
| Low | `reel_factory/caption_render.py` | Renderer is genuinely good (pixel-measured wrap, Apple emoji, safe zones) — but safe zones are hardcoded and it never checks caption contrast against the **actual** video behind it. Sample the underlying region, auto-pick stroke/box for contrast. |

---

## Track S — Anti-shadowban safety (~4/10; INSUFFICIENT against real duplicate detection)

PR #44 made variation real (per-index edits, sibling gate). **But the gate still measures the wrong thing**, and these hold on `main`:

| Sev | File:line | Fix (DETECTION/variation only — NOT spoof-strengthening) |
|-----|-----------|------|
| Fixed | `repurposer/qa/similarity.py`, `campaign_factory/variation_stage.py` | SSIM is diagnostic only. Apply mode gates the full batch on ContentForge PDQ `>40` and SSCD `<0.50` evidence before writing an export-consumable assignment. |
| Fixed | `contentforge/.../similarity/route.js` | `campaign_factory_v1` now makes PDQ/SSCD failures and unavailability blocking. The default ContentForge profile remains advisory. |
| Partial | `contentforge/lib/campaign-factory-audit-config.js` | Campaign Factory variation now supplies every sibling through `comparisonFiles` and blocks sibling collisions. Other ContentForge callers must opt into a scoped comparison set. |
| High | `core.py:11117-11221` | Cross-account `perceptualFingerprint`/`perceptualClusterId` cooldown reads metadata fields that are **never computed** → silently no-ops. Compute + persist real PDQ at render time; add a "PDQ cluster cooldown" alongside the lineage cooldowns. |
| Fixed | `repurposer/config.py`, `engines/audio.py`, `repurposer/pipeline.py` | `ig_subtle` now enables the audio layer, selects catalog-backed replacement audio deterministically by account index, and fails closed when an audio-required preset cannot assign replacement audio. Tests cover per-account selection and missing-audio rejection. |
| Med | `ThreadsDashboard/.../originalitySignals.ts:81-124` | Dashboard's only perceptual hash is weak 64-bit **aHash**, and `fetchPerceptualHash` returns null for video (video gets **no** perceptual signal). Upgrade to PDQ; keyframe-hash video. |
| Good (keep) | `core.py:5256-5311`; `campaignSchedule.ts:1180-1265,441-480` | Caption variation is real per-index; cadence is conservative (warming 1/day@24h … high-perf 2/day@6h + ~12-min cross-account spacing); lineage cooldowns (14d variant/parent, content-fingerprint) enforced + AP0-1 unique index. **The gap is perceptual sameness, not posting rate.** |

**Policy note:** every safety fix above strengthens **detection and legit variation** (catching collisions, gating on the real metric, per-account audio/caption). **None strengthens the `micro` hash-evasion spoof** — that remains off-by-default and owner-directed only. We make the system *catch* collisions, not *hide* them.

---

## Tools to adopt (map to the gaps)

- **Higgsfield `virality_predictor` + `video_analysis`** (already connected) → real virality gate (Track Q).
- **PDQ** (`facebook/ThreatExchange`) + **SSCD** (`facebookresearch/sscd-copy-detection`, model already referenced) → real distinctness metric (Track S); both detectors already in `contentforge/lib`.
- **OpenCLIP / SigLIP** → semantic creative/hook scoring vs winning references (Track Q).
- **PySceneDetect** → real scene-aware editorial variation (Tracks Q+S).
- **Thompson-sampling bandit** or **River** (online ML) → turn ranking into actual learning (Track I).
- **VMAF/CAMBI** → already in `contentforge/lib/quality-metrics.js`, wire as a quality gate (Track Q).

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
2. **Track I capture bugs** (the 3 in the High row) — they corrupt training data at the source; everything "smart" depends on clean capture. Port AP0-2 into the running path.
3. ~~**Track I contract lineage**~~ ✓ **FIXED** — causal IDs are required in the three attribution contracts, with Python/TypeScript negative tests and producer updates.
4. **Track Q quality floor** — minimum-dimension bug and Campaign Factory OCR safe-zone blocking are fixed; real watchability gate (VMAF/audio/crop), readability legibility, and model-backed creative gates remain.
5. **Higgsfield virality wiring** (Track Q) — high-leverage, low effort.
6. ~~**Track I Campaign Factory statistical rigor**~~ ✓ **FIXED** — normalized reward, recency decay, confidence shrinkage, and explicit unmeasured state are in the Campaign Factory scoring seam.
7. Winner-DNA → generation auto-feedback; reference_factory return path.

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
| **Reference Factory** | 6.6 | ~7.8 | Decompose `reference_intake.py` (2858 lines); kill dup `_caption_archetype` / latent KeyError (P1-4); ~80% test coverage on intake + pattern-card path; one declared, tested provider path (no Grok/Ollama doc drift). |
| **Reel Factory** | 7.6 | ~8.3 | Fix `pyproject` module list (P0-1) → deterministic install; wrap Higgsfield/Kling in a tested adapter with recorded fixtures (failure modes handled, not hoped); golden-output tests for caption render + E2 still→MP4 (duration/pixel asserts). |
| **Campaign Factory** | 6.1 | ~7.3 | **Decompose `core.py`** (27k lines / 847 methods) into orchestration / inventory / audit / export / learning modules behind interfaces. Biggest single lever in the system. Maint 4→8 + module-level tests per carved unit. Highest-risk; needs contract tests as a safety net FIRST. |
| **ContentForge** | 7.0 | ~8.0 | Test `similarity/route.js` (1827 lines) + `pipeline.js` (P1-5 untested surface); calibration fixtures — known-collision & known-distinct media pairs asserting PDQ ≤31 / SSCD ≥0.75 hold (catches detector drift). |
| **Autoposter (TD)** | 8.2 | ~9.0 | Land AP0–AP3 (merge ~16 branches, weave `publishInstagram.ts`, re-run CI) — already coded to 9-grade. For true 9: one integration test driving a fake Meta Graph through the full error taxonomy (transient/window_cap/permanent → retry/backoff/dead-letter) + account-health pause/resume loop. |
| **Pipeline Contracts** | 6.7 | ~7.5 | Replace hand-rolled validators with **codegen from the JSON schemas** (→ Python + TS) so the two sides *can't* drift; round-trip property tests per contract; CI byte-sync check enforced, not hoped. |

### The three structural levers (dominate the jump to 9)

1. **`core.py` decomposition** — gates Campaign Factory; nothing else moves its maint score. ~weeks, highest risk. Land strong contract/characterization tests first as the safety net.
2. **Test coverage on the 3 big untested surfaces** — `reference_intake.py`, `similarity/route.js`, `pipeline.js`. These are safety- and learning-critical and under-tested.
3. **Contract codegen** — makes cross-repo drift structurally impossible instead of vigilance-dependent.

### Two ceilings code can't fully fix (state honestly, don't fake)

- **Learning-loop data volume.** F v2 (median-norm + decay + Thompson) is a *better estimator*, not *more data*. Per-arm reward is small-n; the real ceiling needs posting volume × time. That's calendar, not code — caps F ~8.5 until volume arrives.
- **External-gen variance.** Higgsfield/Kling output quality isn't fully in our control. The tested adapter handles *failure*, not *creativity* — caps Reel Factory ~8.5 on the generation axis.

### Suggested 9-grade sequence for Codex (dependency-safe)

1. **Contract codegen first** — it's the safety net the rest leans on; drift-proofs every downstream change.
2. **Characterization tests around `core.py`** before touching it — lock current behavior so the refactor can't silently regress.
3. **Test the 3 untested surfaces** (reference_intake, similarity/route, pipeline.js) — independent, parallelizable, high-value.
4. **ContentForge detector calibration fixtures** — pins PDQ/SSCD thresholds against drift.
5. **Reel Factory adapter + golden-output tests**; fix `pyproject` (P0-1).
6. **`core.py` decomposition LAST** — highest risk, now protected by steps 1–2. One module carved per PR.

Same non-negotiable constraints above apply — especially: `core.py` work is *new modules + characterization tests*, not in-place surgery without a net; one logical change per PR; quality floor only goes up.

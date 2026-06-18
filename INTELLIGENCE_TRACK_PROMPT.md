# Intelligence Track — Codex prompt (make it *smart*, make it *great*)

**Context for the owner (not part of the prompt):** Track S (anti-shadowban PDQ/SSCD blocking gate) already SHIPPED on creator-os `main` (PR #54). This prompt covers the other two intelligence tracks from `INTELLIGENCE_AUDIT.md`:
- **Track I** — close the learning loop (4/10): clean the training data at source, stop dropping lineage at the contract boundary, then make ranking a real normalized + decayed + confidence-weighted reward (Workstream F v2).
- **Track Q** — content quality / virality (3/10): turn the computed-but-ignored quality/virality signals into real blocking gates.

**Spans two repos.** Capture-bug fixes + the weak perceptual hash live in **ThreadsDashboard**; lineage contracts, ranking, quality gates, F v2, and reference-factory feedback live in **creator-os**. Each PR below says which repo. Full detail + every file:line is in `INTELLIGENCE_AUDIT.md`.

---

## Prompt to give Codex

> **Two repos:** creator-os (pipeline; `core.py`, `repurposer/`, `contentforge/`, `pipeline_contracts/`, `reference_factory/`) and ThreadsDashboard (capture path; `analyticsSync.ts`, `post-engagement.ts`, migrations). Work on feature branches off each repo's `main`; open PRs; never push to `main` directly. creator-os `main` is protected (required CI: contracts/architecture/hygiene/secret-scan/scorecard/CodeQL/python/javascript/sbom). One logical change per PR; each PR adds the test that proves it; `pnpm check:contracts` green after any schema change.
>
> **Goal:** raise Intelligence 4→8 and Quality 3→7. The pattern across both: **real signals are computed and then ignored** — the fix is mostly *wiring + statistics*, not building. Do it in this dependency order — a learning loop on corrupt data learns garbage, so data integrity comes first.
>
> ### PR 1 — fix the 3 capture bugs (ThreadsDashboard) — DO FIRST
> These corrupt training data at the source; everything "smart" downstream depends on clean capture.
> - **Monotonic guard** `supabase/migrations/20260307210000_monotonic_metric_updates.sql:36-41`: guard compares views-inclusive vs views-exclusive → the per-post 24h UPDATE silently no-ops. Fix the comparison so 24h metrics actually land.
> - **Retention delete** `analyticsSync.ts:716`: 90-day cleanup does `delete().lt("created_at", …)` but the column is `snapshot_at` → errors every run, swallowed, table grows unbounded. Fix the column; assert the delete succeeds.
> - **Threads reach/saves** `post-engagement.ts:130-142`: `reach` and `saves` are never written (always 0) yet the score weights them. Capture them, or remove them from the weighting until captured.
> Each fix gets a test asserting the corrected value persists. Also port the AP0-2 `postMetricSnapshotReconciliation` into the running path if not already (it backfills dropped windows; doesn't touch these 3 bugs).
>
> ### PR 2 — stop dropping lineage at the contract boundary (creator-os)
> The internal SQLite carries full lineage (`post_id`/`variant_id`/`concept_id`); the **exported contracts drop it**, so Workstream F can't attribute performance to cause.
> - In `generated_asset_lineage.v1` / `recommendation_accuracy_report.v1` / `performance_sync.v1`: make the lineage IDs **`required`** (they're bare `{"type":"object"}` today). Add a contract test that drops an ID and asserts validation **fails**.
> - `adapters/threadsdash.py:2696-2699`: TD→Python sync silently drops any post missing `metadata.campaign_factory` (`skipped += 1; continue`) — log/dead-letter instead so the loss is visible.
> - `adapters/threadsdash.py:3004`: handoff reads the canonical `posts` row only, never `post_metric_history` — pull the **time-series** so F sees velocity/retention, not one point.
> - New schema version if payload shape changes; keep compat copies byte-synced.
>
> ### PR 3 — real quality floor (creator-os, Track Q)
> The entire "quality floor" is `repurposer/qa/quality.py is_quality_acceptable` → `if width<720 and height<720: return False` (**both** must fail — a 720×404 clip passes). Replace with a real watchability floor using machinery that **already exists**:
> - Wire `contentforge/lib/quality-metrics.js` `runVmaf`/`cambi` (VMAF/CAMBI banding — currently unused) + audio loudness (LUFS) + subject-crop check.
> - `contentforge/.../similarity/route.js:16,343-348`: `creativeQuality`/`safeZone`/`readability`/`hookVisibility` are hard-excluded from blocking. Promote the real OCR **safe-zone** signal to blocking; fix or retract the README's false "enforce a quality floor" claim.
> - `route.js:1395`: add the font-height÷frame-height term to `readabilityScore` (today tiny-but-crisp text scores "readable").
> - **Quality floor only goes UP** — no change may lower delivered quality.
>
> ### PR 4 — wire Higgsfield virality (creator-os, Track Q) — high-leverage, low-effort
> `virality_predictor` is available in-environment and gates nothing. Plug in at two points:
> - **ContentForge**: new **blocking-capable** `virality` layer.
> - **reel_factory** post-render QC: auto-reject/down-rank low-predicted-virality clips **before** posting.
> Also replace `contentforge/lib/creative-quality-audit.js:237` (`heuristic_v1` keyword-bag hook scoring, `modelBacked:false`) with a VLM judge (Higgsfield `video_analysis`) scoring first-3s frames + OCR'd hook against winning archetypes. Converts "is it postable" → "will it perform."
>
> ### PR 5 — statistical rigor: ranking → learning (creator-os, Workstream F v2)
> Today ranking is raw-count, no normalization, no decay, no confidence (`core.py:14732` `max(views)`, `:25378` `_performance_quality_score` linear sum of raw averages, `patterns.py:569-603` `log10(plays)` on absolute counts). Build the F v2 reward per the `INTELLIGENCE_AUDIT.md` blueprint:
> - **Reward** = `relative_perf = post_engagement_rate / account_trailing_MEDIAN` (median, not mean — engagement is heavy-tailed). Replaces raw `max(views)`.
> - **Bayesian shrinkage** toward prior 1.0, `prior_strength≈5`: `shrunk = (5×1.0 + n×mean)/(5+n)` — kills lucky-first-post; carry an explicit **"unmeasured"** state (not `50`=average, per `core.py:23197`/`22504`).
> - **Recency decay**: `weight = 0.5^(age_days/21)`, `effective_n = Σweight` → unused arms re-widen → auto re-explore.
> - **Arms** = independent per-dimension bandits (hook type / preset / reference-pattern). **≥15% exploration floor.**
> - **Algorithm**: v1 = ranking with confidence (lower-bound); v2 = Thompson sampling at volume. Single SQLite table of per-arm decayed stats, O(K)/decision, updated on 1h then 24h pull.
> - **Honest ceiling:** this is a better *estimator*, not more *data* — per-arm n is small; real performance gain needs posting volume × time. State that; don't over-claim.
>
> ### PR 6 — close the reference_factory feedback loop (creator-os)
> `reference_factory` is one-directional (scrape→score→emit), no feedback (scores ~2/10 alone). Add outcome columns to `generated_video_prompts` (`db.py:296`) so it ranks patterns by **our** measured results, not competitor leaderboard order. Feed Winner-DNA (`reel_factory/winner_dna.py:30-45`) — winning scene/pose/motion/caption-archetype — directly into prompt assembly instead of dead-ending as an operator note; upgrade extraction to VLM on the actual winning videos.
>
> **Non-negotiable constraints (from `INTELLIGENCE_AUDIT.md`):**
> - **Legit variation + detection only — do NOT strengthen the `micro` hash-evasion spoof.** (Track S already shipped the detect-and-respect gate; don't touch evasion.)
> - **Quality floor only goes UP.** No change lowers delivered quality.
> - **Dashboard fixes go upstream to ThreadsDashboard.** creator-os does not edit a dashboard mirror.
> - **Contracts in sync:** `pnpm check:contracts` green; new cross-package data → new versioned schema.
> - **No regressions** to the working back half (export/schedule/publish/feedback).
> - **`core.py` is a 27k-line god-class** — new logic in **new modules**, thin seam only; don't grow it.
> - One logical change per PR; tests green; each fix adds the test that proves it.

---

## Sequencing rationale (for the owner)

1. **Capture bugs first** — clean data is the precondition; a bandit on corrupt reward learns garbage.
2. **Lineage next** — F can't attribute performance without IDs; it's F's hard precondition.
3. **Quality + virality** — independent of the loop, high-leverage, parallelizable with 1–2.
4. **F v2 rigor** — needs 1 + 2 done first; turns ranking into learning.
5. **Feedback loop** — last; closes reference_factory + Winner-DNA into generation.

**Repo split:** PR 1 = ThreadsDashboard. PRs 2–6 = creator-os. Track S (the safety gate) is already shipped — this track is *smart* + *great*, not *safe*.

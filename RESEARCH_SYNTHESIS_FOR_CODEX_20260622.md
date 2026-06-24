# Research Synthesis — For Codex Review (2026-06-22)

Context: we ran 3 research prompts (each on both ChatGPT and Claude) to find open, **commercial-use-OK** models/approaches for the autonomous IG→OnlyFans pipeline. Below is Claude-Code's vetted synthesis (with the load-bearing facts independently verified on Hugging Face / web). **Pattern across all three: Claude's reports were rigorous and license-careful; ChatGPT's were directionally right but repeatedly wrong/loose on licenses** (called DOVER "MIT" — it's non-commercial S-Lab; missed DINOv3's non-Apache license). For a commercial OF business, license is the gate.

**What we want from Codex:** your opinion on each recommendation *against the actual codebase* — feasibility, where each plugs in, what's already half-built, what you'd sequence differently, and any disagreement with the picks.

---

## Verified license facts (checked, not assumed)
- **DOVER / FAST-VQA / Q-Align** = S-Lab License 1.0 → **NON-COMMERCIAL. Exclude.** (DOVER is S-Lab/NTU, built on FAST-VQA.)
- **COVER** (taco-group, CVPRW 2024) = MIT (verify LICENSE file) → commercial OK. The DOVER replacement.
- **DINOv3** = `license:other` (custom Meta license, gated, "Built with DINOv3" attribution) → **use DINOv2 (clean Apache-2.0) instead.**
- **jina-embeddings-v3** = CC-BY-NC (non-commercial) → avoid; use Qwen3-Embedding (Apache) or BGE-M3 (MIT).
- Confirmed commercial-safe: SigLIP/SigLIP2, DINOv2, Falconsai NSFW, Marqo-384 NSFW, Bumble Private Detector, LAION aesthetic predictor (all Apache/MIT/BSD); MABWiser (Apache), Vowpal Wabbit (BSD-3), PyMC/NumPyro (Apache).

---

## Prompt 1 — Pre-post reel quality + COMPLIANCE gate

**Boundary (agreed):** block-when-risky compliance, NOT tune-to-the-takedown-line. No ban-evasion, no hash-spoofing, no threshold-prediction. Uncertain → human review.

**Stack (commercial-safe):**
- Aesthetic: **LAION improved-aesthetic-predictor** (Apache). Score the 20th-percentile frame, not the mean.
- Technical video: **COVER** (MIT). NOT DOVER/FAST-VQA/Q-Align (non-commercial).
- Compliance (NSFW): ensemble **Marqo-384** (only one trained on AI-generated imagery → lead) + **Falconsai** (volume) + **Bumble Private Detector** (tuned against false-positives on suggestive-but-clothed). Optional **NudeNet** (AGPL; fine self-hosted) for per-body-part granularity.

**Gate design:** three-way verdict — auto-OK / route-to-`needs_review` / hard-block. Compliance is a **veto**, not a weighted average. Fail-closed on any model error/disagreement. The "suggestive-but-uncertain" band (the majority for OF-persona content) always → human review.

**Honest core:** no open model maps to Instagram's actual policy line — these are RISK signals, not verdicts. Roll out in **shadow mode** (score already-posted reels, compare to real takedown outcomes) before enabling auto-OK. Biggest accuracy lever = fine-tune Marqo/Falconsai on a few thousand of your own reel frames labeled to your policy (AI-generated content degrades most NSFW models).

**Where it plugs in:** ContentForge already samples frames for OCR/safe-zone — natural home. Verdict routes into the existing `review_batch_guard` / `needs_review` checkpoint. Florence-2 (already in pipeline) gives the reviewer scene context.

---

## Prompt 3 — Replace heuristic "winner DNA" with real embedding-based learning

(Reference Factory today = keyword regex + frequency clustering; it relabels against a fixed taxonomy, can't discover new winners.)

**Stack (commercial-safe, runs local on the Mac Studio):**
- Images: **DINOv2 ViT-L/14** (Apache — style/"vibe") + **SigLIP 2 so400m** (Apache — semantic). NOT DINOv3.
- Captions: **Qwen3-Embedding-0.6B** (Apache) or **BGE-M3** (MIT). NOT jina-v3.
- Pipeline: L2-normalize per modality → weighted concat (image-heavy) → **UMAP → HDBSCAN** (not k-means: no fixed k, finds new patterns, noise handling).

**The point that matters most:** rank clusters by **empirical-Bayes-shrunk** performance, not raw average. With a few thousand posts over many clusters, a tiny cluster with one viral post fakes a 100% rate. Shrinkage pulls small clusters toward the global mean → you don't chase noise. Add recency-weighted velocity to flag *emerging* winners. (ChatGPT's "t-test" is the weak version.)

**Feedback:** cluster medoids → reference images for Higgsfield/Kling; cluster keywords (c-TF-IDF) + VLM caption of medoids → prompt template. Embed → cluster → rank-by-performance → feed generation. **Independent of the funnel — can start now.**

---

## Prompt 2 — Optimize for OnlyFans CONVERSION, not views (the brain)

**Start simple, gate on data:**
- Phase 1: **Beta-Bernoulli Thompson sampling** over discretized arms (caption archetype × visual style × account × time bucket), rewarded on a **click proxy** (clicks-per-view) — NOT conversions (too sparse early). Blend toward conversions as they accrue (~40 positives/arm gate).
- Do NOT start with contextual bandits or uplift modeling — both data-starved at a few hundred posts / few conversions. Graduate to contextual (Vowpal Wabbit CB-ADF) + hierarchical pooling later.

**Two failure modes ChatGPT missed (load-bearing):**
1. **Delayed/censored conversions.** OF signups arrive hours-to-weeks after the post. A naive bandit reads "no conversion yet" as failure and **punishes slow-converting, often higher-value, arms.** Fix = delay-corrected estimator (Vernade/Chapelle) before conversions drive selection.
2. **Account over-fitting.** One high-traffic account dominates pooled "winners." Fix = **hierarchical partial-pooling** (account as random effect, shrinks small accounts toward the group), not flat context.

**Attribution (Phase 0, prerequisite):** HMAC click-ID → server-to-server postback, idempotent dedup, arm encoded in sub-ID/UTM. **This Phase 0 IS funnel-v1's OF-conversion-postback work — same chain, not extra.** Libs all commercial-safe (MABWiser/VW/PyMC).

---

## Sequencing + one convergence

- **Winner-DNA (Prompt 3): start now** — local, no funnel dependency, improves content quality.
- **Funnel-v1 (smart links + OF postback)** unblocks the bandit (its Phase 0 = the funnel's attribution chain).
- **Bandit (Prompt 2): wire the click proxy first** (available as soon as links get clicked), conversions + delay-correction after they accrue.
- **Quality/compliance gate (Prompt 1):** build alongside; routes into the existing `needs_review` checkpoint; shadow-mode before auto-OK.
- **Convergence:** the bandit and winner-DNA are the **same statistical engine at different grain** (both want shrunk conversion rates / Thompson + empirical-Bayes). Build **one conversion-attribution feed** that serves both — don't stand up two reward pipelines.

---

## Questions for Codex
1. For each stack — where does it plug into the *actual* code (ContentForge gate? Reference Factory? a new service? TD's `performanceFirst`)? Anything already half-built we'd reuse?
2. The funnel-v1 attribution chain (HMAC click-ID → postback) already partly exists (`go/convert.ts`, `smart_links`, `performanceFirst` reads conversions). What's the minimal delta to make it the bandit's Phase-0 feed?
3. Do you agree winner-DNA can start independently, or does it need the conversion feed first to be worth it (since reward = conversions)?
4. Any of the picks you'd swap given the repo's existing deps / runtime (Python packages, MPS on the Mac, the Vercel/TD side)?
5. Where would you put the single shared conversion-attribution feed so both ContentForge-side learning (creator-os) and TD's `performanceFirst` consume it without a second pipeline?

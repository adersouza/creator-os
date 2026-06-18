# Research 05 — Learning-Loop / Bandit Design (2026)

> Owner-supplied research + system design. The concrete, lightweight, local blueprint for Workstream F and the INTELLIGENCE_AUDIT Track-I fixes.

## Core architecture
Treat each lever as a categorical dimension with discrete options: **hook type** (question/bold-claim/POV/listicle), **preset** (visual style), **reference-pattern** (structural template). A post = one value per dimension. Estimate expected reward per option, bias production toward winners, keep exploring.

## Reward normalization (nail this first — everything inherits its noise)
- **Account-size:** compare each post to *that account's own trailing baseline*, not absolute views:
  `relative_perf = post_engagement_rate / account_trailing_MEDIAN_engagement_rate`
  (1.0 = typical, 2.5 = 2.5× normal). **Median, not mean** — engagement is heavy-tailed; one viral post wrecks a mean. Makes small/large account breakouts comparable; auto-adjusts as accounts grow. **Replaces raw `max(views)` ranking.**
- **Don't collapse to one gameable ratio.** `engagement/reach` flatters low-reach posts. Reward `log(reach) × engagement_rate`, or track reach and rate as two signals.
- **1h→24h surrogate:** fit `24h_perf ~ 1h_perf` regression once offline. Use 1h *predicted* reward immediately (same-day responsiveness), replace with actual 24h when it lands. Makes the loop feel responsive instead of glacial.

## Decision algorithm — honest comparison
| Approach | Sample-eff | Sparse-data | Compute | Implement | Interpret |
|----------|-----------|-------------|---------|-----------|-----------|
| Raw mean ranking | low | poor (no uncertainty) | O(K) | trivial | high | **← don't start here**
| Ranking + confidence (LCB / credible interval) | good | good | O(K) | easy | high | **← ship this v1**
| Thompson sampling (Beta/Gaussian) | very high | high | O(K) | moderate | high | **← v2 at volume**
| UCB1 | good | moderate | O(K) | moderate | moderate |
| Contextual (LinUCB) | very high | good | O(K·d²) | complex | low | **← phase 2 (interactions)**

**Recommendation:** ranking *with confidence* gets 80% of bandit value, more interpretable → v1. Move to **Thompson sampling** (Beta-Bernoulli on "beat trailing-median: yes/no", or Gaussian on `relative_perf`) when volume makes explore/exploit losses matter. Never start with raw-mean ranking — missing uncertainty is what burns you.

## Confidence as a weight (fixes "confidence-as-label" + "missing=50")
- **Bayesian shrinkage toward prior 1.0**, `prior_strength≈5`:
  `shrunk = (5×1.0 + n×observed_mean) / (5 + n)`
  New arm sits near the global average until evidence accumulates → kills the lucky-first-post problem; unmeasured arms are NOT faked as "average 50."
- Or **LCB (pessimistic):** rank by `mean − z·std/√n`; few-sample arms penalized for uncertainty.

## Recency decay (fixes "zero recency decay")
- `weight = 0.5 ** (age_days / half_life)`, half-life **~14–30d (start 21d)**.
- Maintain decayed running stats per arm: `effective_n = Σ weight_i`, `weighted_mean = Σ(weight_i·perf_i)/effective_n`.
- Elegant: `effective_n` shrinks when an arm goes unused → posterior re-widens → **auto re-explore** stale arms. One row per arm, incremental update.

## Combinations without explosion
- v1: **independent per-dimension bandits** (best hook + best preset + best pattern, combined). Ignores interactions, needs far less data, ~90% as good.
- Phase 2: small contextual model (one-hot dimension features + account context) for interactions.

## Exploration & cold-start
- Keep an **exploration floor ≥15%** of production so no arm dies permanently.
- New arm/account: init at prior (global mean), force a round-robin first trial, share priors across similar accounts (hierarchical).
- Small accounts: heavier shrinkage + exploration. Large: lean on data.

## Pseudocode (Thompson, Beta-Bernoulli)
```
For each arm a: α[a]=1, β[a]=1
On each decision:
  sample θ[a] ~ Beta(α[a], β[a]) for all a
  pick arm = argmax θ
On reward r∈{0,1} ("beat trailing-median"):
  α[arm]+=r ; β[arm]+=(1-r)
  (apply recency decay to α,β before update)
```

## What to ship (v1)
Single SQLite table of per-arm decayed stats, updated on each post's 1h then 24h pull. Beta-Bernoulli Thompson on "beat trailing-median baseline", exp recency decay (~21d half-life), independent per-dimension, ≥15% exploration floor. A few hundred lines, local, no infra. Validate with offline replay on historical logs before rollout.

**Precondition:** fix the 3 metric-capture bugs (monotonic guard, dead retention delete, Threads reach/saves always 0) first — a bandit on corrupt reward data learns garbage.

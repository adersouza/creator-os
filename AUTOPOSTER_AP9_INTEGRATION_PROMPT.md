# AP9 Integration Prompt — merge the 5 AP→9 branches into TD main

**Audience:** Codex + owner. **Repo:** ThreadsDashboard. **Context:** the autoposter 8.7→9 lift (`AUTOPOSTER_AP9_PROMPT.md`) is BUILT — all 5 PRs exist on independent branches, verified locally, but none are on TD `main` (currently the AP0–AP3 merge `ec2190b5e` or later). This is the same situation AP0–AP3 was in before the `codex/autoposter-hardening-complete` weave: independent branches that need a deliberate integration pass.

## The 5 branches to land

| AP9 PR | Branch | Tip | Touches |
|--------|--------|-----|---------|
| 1 — IG failure-branch e2e | `codex/autoposter-ap9-1-ig-failure-e2e` | `b1cdb832a` | `e2e/publish-instagram.spec.ts`, `e2e/post-lifecycle.spec.ts` (mirror Threads failure harness) |
| 2 — publish-claim concurrency | `codex/autoposter-ap9-2-publish-claim-concurrency` | `06da9db23` | publish-claim test (`scheduled→publishing` atomic claim under parallel workers) |
| 3 — alerting signals | `codex/autoposter-ap9-3-alerting-signals` | `abdd4ee5e` | `alerting.ts` callers — AP3 pause/resume, publish DLQ growth, AP2 run-report anomaly |
| 4 — merge-debt cleanup | `codex/autoposter-ap9-4-merge-debt-cleanup` | `e4a16cc83` | `publishInstagram.ts` / `publishPost.ts` dedup + the 13 lint warnings |
| 5 — token-rotation story | `codex/autoposter-ap9-5-token-rotation-story` | `33be1d1e9` | `docs/autoposter-token-rotation.md` + `tests/unit/token-rotation-story.test.ts` (docs/tests only — no runtime gap found) |

## Prompt to give Codex

> **Repo:** ThreadsDashboard. Land all 5 `codex/autoposter-ap9-*` branches on `main` via a single deliberate integration pass (mirror the `codex/autoposter-hardening-complete` weave that landed AP0–AP3). Never force-push `main`; do it on an integration branch → PR → CI → merge.
>
> **Order (least-conflict first):**
> 1. **PR 5 (token rotation)** — docs + tests only, zero runtime overlap. Land first, free.
> 2. **PR 1 (IG failure e2e)** — e2e specs only; no runtime overlap. 
> 3. **PR 2 (concurrency test)** — adds a test; touches no runtime. 
> 4. **PR 3 (alerting signals)** — wires `alerting.ts` calls into AP3/AP2/DLQ paths; small runtime surface.
> 5. **PR 4 (merge-debt cleanup)** — LAST, because it rewrites `publishInstagram.ts`/`publishPost.ts`; rebase it on top of 1–3 so its cleanup reflects the final state. This is the only real conflict point — resolve by keeping PR4's deduped version and re-applying any alerting hooks from PR3 on top.
>
> **At each step:** rebase the branch on the current integration HEAD, resolve conflicts (expected only in PR3↔PR4 on the publish path), run the targeted `vitest` autoposter suite + `compat:check` + `typecheck` + `build`, confirm green before stacking the next.
>
> **Final gate before merging to `main`:**
> - Full autoposter targeted suite green (the union of all 5 branches' tests — IG failure branches, concurrency claim, alerting, token rotation).
> - `lint` exits 0 with **zero** warnings (PR4 clears the 13 inherited ones — verify on the integrated branch, not each branch's stale base).
> - `compat:check` + `typecheck` + `build` green.
>
> **Constraints:**
> - No posting-behavior or evasion change — this is verification/observability/cleanup only.
> - Don't loosen any gate. Alerting is additive; cleanup is behavior-preserving.
> - One integration branch → one PR; the PR description lists all 5 source commits.
>
> **Done = autoposter on TD main at a confident 9:** failure branches proven for both platforms, double-publish proven impossible under contention, degradation paged to Discord, publish path deduped + lint-clean, token rotation documented + tested.

## After this lands

Update `autoposter_map.html` (flip the AP→9 item from 🔧 in-progress to ✓ shipped) and `creator_os_map.html` (dashboard 8.7→9.0, the `9-ap` roadmap item already done for AP0–AP3 → extend note to AP→9). The autoposter is then the first part of the system at a clean 9.

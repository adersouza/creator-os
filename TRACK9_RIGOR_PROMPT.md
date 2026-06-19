# Track 9 — Rigor Prompt (the test + drift-proofing lift to ≥9)

**Audience:** Codex + owner. **Source:** `INTELLIGENCE_AUDIT.md` Track 9. **Companion:** the `core.py` decomposition is the single biggest item and has its own detailed plan in `CORE_PY_DECOMPOSITION_PLAN.md` — this prompt covers the **other** Track-9 rigor items (the ones that are roadmapped but weren't yet executable).

**The premise:** the capability tracks (Intelligence, Quality, AP) lift each part to ~7–8. The jump to **≥9** is engineering rigor — **tests + drift-proofing**, not features. These items are independent, mostly parallelizable, and low-risk.

## Execution ledger

All Track-9 rigor PRs are now landed on `origin/main` as of 2026-06-19:

| PR | Status | Merge commit | Outcome |
| --- | --- | --- | --- |
| PR 1 — contract codegen / schema drift-proofing | Landed before this execution window | See `packages/pipeline_contracts` generated schema/runtime-import history and `pnpm check:contracts` gate | Drift checks and generated schema/runtime import path established before deeper rigor/core work. |
| PR 2 — test `reference_intake.py` | Merged in PR #189 | `429c422` | Added focused Reference Factory intake rigor coverage; `reference_factory.reference_intake` coverage moved 77% -> 80%; pinned the known caption-archetype regression without changing runtime behavior. |
| PR 3 — test ContentForge similarity route + pipeline | Merged in PR #191 | `ed96da0` | Added regression coverage for detector failure posture, blocking-vs-advisory decisions, comparison-set behavior, and image pipeline quality-gate rejection accounting. |
| PR 4 — ContentForge detector calibration fixtures | Merged in PR #192 | `12256dc` | Added PDQ/SSCD/TMK calibration fixtures and threshold assertions, plus additive machine-readable temporal detector thresholds. |
| PR 5 — Reel Factory adapter + golden tests | Merged in PR #193 | `95a2a50` | Added a tested Higgsfield CLI adapter with timeout/partial/quota fixtures, packaging metadata coverage, caption safe-zone wrapping checks, and still-to-MP4 ffprobe golden assertions. |

Follow-up posture: this prompt is now historical/completed for PRs 1-5. Continue production-grade work through `CORE_PY_DECOMPOSITION_PLAN.md`; keep each future `core.py` extraction behind characterization/focused behavior tests and green repo gates.

---

## Prompt to give Codex

> **Repo:** creator-os (monorepo; pnpm + uv + turbo). `main` is protected — feature branch → PR; required CI: contracts/architecture/hygiene/secret-scan/scorecard/CodeQL/python/javascript/sbom. One logical change per PR; each PR adds the test that proves it; `pnpm check:contracts` green after any schema change.
>
> **Goal:** the Track-9 rigor lift — make cross-repo drift impossible and put real test coverage on the three big untested surfaces + the perceptual detectors. Five PRs, roughly this order (1 first — it's the safety net the others lean on):
>
> ### PR 1 — contract codegen (drift-proof the contracts) — DO FIRST
> The `pipeline_contracts` validators are **hand-rolled** in both `packages/pipeline_contracts/pipeline_contracts/__init__.py` (Python) and `packages/pipeline_contracts/typescript/index.ts` (~12 hand-coded TS validators). Two hand-maintained sides drift. (Codex PR #60 already made lineage IDs `required` + added `test_validator.py` / `typescript-validator.test.ts` — good, but the validators are still hand-written.)
> - **Generate** the Python + TS validators from the canonical `schemas/*.json` (16 contracts) — a small codegen step run in CI, output checked in or built. The two sides can no longer disagree because they're generated from one source.
> - Add **round-trip property tests** per contract: example payload → validate → serialize → re-validate, plus a negative case per `required` field (drop it → assert failure).
> - Add a **CI byte-sync check** that fails if the compatibility schema copies (the repo keeps multiple `schemas/` mirrors — `packages/`, `pipeline_contracts/`, `python_packages/campaign_factory/schemas/`) drift from canonical. Make drift a red build, not vigilance.
> - **Contracts 6.7 → 7.5.**
>
> ### PR 2 — test `reference_intake.py` (creator-os, reference_factory)
> `reference_factory/reference_intake.py` (~2858 lines) is the largest untested surface and feeds all downstream "smart." Bring it to ~80% coverage: the intake/parse/normalize path, the pattern-card emit, the audio-catalog build. Pin the known bug first — the duplicate `_caption_archetype` / latent `KeyError` (P1-4) — with a regression test. **Reference Factory 6.6 → 7.8.**
>
> ### PR 3 — test `similarity/route.js` + `pipeline.js` (ContentForge)
> `contentforge/.../similarity/route.js` (~1827 lines) and `pipeline.js` (~800 lines) are safety-critical (they run the PDQ/SSCD distinctness gate shipped in Track S) and under-tested (P1-5). Cover the routing, the blocking-vs-advisory decision, the comparison-set assembly, and the quality-floor guards. **ContentForge 7.0 → ~7.7** (calibration in PR 4 finishes it to 8.0).
>
> ### PR 4 — ContentForge detector calibration fixtures
> Pin the perceptual thresholds against drift. Add fixtures of **known-collision** and **known-distinct** media pairs and assert the detectors hold the research-backed thresholds: PDQ Hamming ≤31 = match (gate at >40), SSCD cosine ≥0.75 = copy (gate at <0.50), TMK ≥0.7. If a detector or model update silently shifts behavior, this test goes red. Protects the Track-S safety property. **ContentForge → 8.0.**
>
> ### PR 5 — Reel Factory adapter + golden tests
> - Fix `reel_factory/pyproject.toml` module list (P0-1: lists nonexistent modules → fresh install fails). Deterministic install.
> - Wrap the external Higgsfield/Kling calls (`generate_assets.py:101/123`) in a **tested adapter** with recorded fixtures, so failure modes (timeout, partial, quota) are handled and asserted, not hoped.
> - **Golden-output tests** for `caption_render.py` (pixel-measured wrap, safe zones) and the E2 still→MP4 path (`still_to_reel` — duration / aspect / frame asserts).
> - **Reel Factory 7.6 → 8.3.**
>
> ### (Separate, biggest) — `core.py` decomposition
> Not in this prompt — see `CORE_PY_DECOMPOSITION_PLAN.md`. It's the highest-risk, highest-value item (caps Campaign Factory) and needs its own module-boundary map + characterization-test net. Do PR 1 here (and the char-test net in that plan) **before** touching `core.py`.
>
> **Non-negotiable constraints:**
> - `core.py` is a 27k-line god-class — any new logic goes in **new modules**, never grow it (the decomposition plan handles the existing mass).
> - Quality floor only goes UP; detector calibration only tightens or holds, never loosens.
> - Contracts in sync: `pnpm check:contracts` green; new cross-package data → new versioned schema.
> - No behavior regressions to the working back half.
> - One logical change per PR; tests green; each fix adds the test that proves it. These are **test/drift PRs — no capability change.**

---

## Why this order (for the owner)

- **Codegen first** — it's the drift safety net; once validators are generated, every later contract change is protected automatically.
- **Surface tests (2, 3)** — independent, parallelizable; highest coverage-per-effort on the riskiest untested code.
- **Calibration (4)** — pins the Track-S safety thresholds so a model/dep bump can't silently weaken distinctness.
- **Reel adapter (5)** — turns the external-gen dependency from a hope into a handled failure mode.
- **core.py decomposition** — last and separate; the riskiest, gated behind PR 1 + characterization tests.

## Ceilings these PRs do NOT remove (honest)

- **Learning-loop data volume** — F v2 (shipped via Codex PR #63) is a better estimator, not more data; caps ~8.5 until posting volume × time accrues. Calendar, not code.
- **External-gen variance** — the PR-5 adapter handles *failure*, not *taste*; Higgsfield/Kling creativity isn't fully controllable.

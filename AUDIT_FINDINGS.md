# Creator OS — Audit Findings & Remediation Plan

**Audience:** Codex (autonomous coding agent) and human reviewers.
**Date:** 2026-06-17
**Method:** 6 parallel read-only audit agents (one per component) + live health checks on branch `sync/td-views-fix`. No code was modified during the audit.

---

## ⚠️ Scope — read this first (do not delete this file)

This document is an **engineering-quality backlog**. It is **NOT**:
- a merge gate for PR #38 or any sync/integration PR,
- a production-runtime promotion or deployment instruction,
- a claim that CI is red.

CI on this branch is **green**, and that is correct. **Green CI does not refute the findings below** — the CI suite (contract sync, arch boundaries, lint/compile, visual regression, mirror parity, secret scan, SBOM) does **not** test packaging installability, FastAPI auth, validator schema-rigor, maintainability, or product/ethics concerns. Those are exactly what this backlog tracks. Per `AGENTS.md`, this branch is a source-integration branch; nothing here blocks integrating it. Work these items as ordinary follow-up, on their own branches, not as a precondition for the sync.

If a finding here is genuinely refuted by evidence, **correct or annotate the specific item** — do not delete the document.

---

## How to use this doc

1. Do **not** edit `apps/dashboard/**`. It is a generated read-only mirror (`apps/dashboard/MIRROR_PROVENANCE.json`). Dashboard fixes go upstream to ThreadsDashboard (TD), then re-sync. Items tagged **[mirror→upstream]** apply.
2. After any contract/schema change, run `pnpm check:contracts` (must stay green).
3. Run the relevant package test suite after each fix (commands in README "Quick Health Check").
4. One logical fix per commit. Conventional Commits. Do not bundle unrelated items.

---

## Scorecard (baseline — for regression tracking)

| Component | Code | Tests | Docs | Maint | Security | Avg |
|---|---|---|---|---|---|---|
| dashboard (Juno33/TS) | 8 | 9 | 9 | 7 | 8 | 8.2 |
| reel_factory (Py) | 7 | 8 | 8 | 6 | 8 | 7.4 |
| contentforge (Node) | 7 | 6 | 8 | 6 | 7 | 6.8 |
| shared infra/contracts | 6 | — | 4 | — | 7 | 6.7 |
| reference_factory (Py) | 6 | 7 | 6 | 6 | 8 | 6.6 |
| campaign_factory (Py) | 4 | 7 | 6 | 3 | 7 | 5.4 |

Infra sub-scores: Contracts 6 · CI/CD 8 · Arch-guards 8 · Monorepo-config 7 · Doc-hygiene 4 · Sec-tooling 7.
**System overall: ~7/10.**

---

## Already fixed (do not redo)

- **Turbo test env passthrough** — root `pnpm test` failed under Turbo strict env because ContentForge OCR tests couldn't see the local toolchain. Fixed in commit `e391c76 fix(turbo): pass through test toolchain environment` (`turbo.json`). ✅

---

## P0 — Blocking

### P0-1. reel_factory packaging is broken (install fails)
- **Location:** `python_packages/reel_factory/pyproject.toml`
- **Problem:** `[tool.setuptools] py-modules` lists four modules that do not exist: `media_qc`, `photo_reel`, `vlm_florence`, `vlm_ollama`. A clean build/install breaks. (CI does not run `pip install -e .`, so green gates do not cover this.)
- **Also:** `requirements.txt` (opencv, watchdog, yt-dlp) disagrees with `pyproject` dependencies — installs differ by path. No version pins in `pyproject`.
- **Fix:** Remove the four nonexistent entries from `py-modules`. Reconcile `requirements.txt` ↔ `pyproject` into one source of truth (prefer `pyproject`). Add version pins.
- **Verify:** `cd python_packages/reel_factory && pip install -e .` succeeds; `python -m pytest -q tests/` (320 tests) stays green.

### P0-2. No auth on any local FastAPI surface
- **Locations:** `python_packages/campaign_factory` (73 endpoints), `python_packages/reel_factory` (server module), `python_packages/reference_factory` (frame endpoint).
- **Problem:** Endpoints expose full read/write plus ffmpeg/subprocess execution surface. Only protection is `127.0.0.1` bind. A single misconfig (`--host 0.0.0.0`, container port-forward, reverse proxy) exposes the entire surface unauthenticated.
- **Why it matters:** Highest blast radius in the system.
- **Fix:** Add a shared auth dependency (bearer token from env, e.g. `CREATOR_OS_API_TOKEN`) as a FastAPI `Depends` on all routers. Reject when token unset AND bind is non-loopback (fail-closed). Keep localhost dev ergonomic: allow loopback without token only if an explicit `ALLOW_INSECURE_LOCAL=1` is set.
- **Verify:** New tests — request without token on non-loopback bind returns 401; loopback dev path still works.

---

## P1 — Should fix

### P1-1. Dashboard: 319 routes bypass RLS via service-role client **[mirror→upstream]**
- **Location:** ThreadsDashboard upstream (reflected in `apps/dashboard`).
- **Problem:** Most routes use the RLS-bypassing service-role client; cross-tenant authorization depends on app-layer discipline (`getAccountIdsForContext`/wrapper guards), not the database. One missed wrapper = cross-tenant data exposure.
- **Existing mitigation:** CI checks `check-rls-first-routes.mjs` + `check-privileged-db-boundaries.mjs` require explicit `PRIVILEGED_DB_REASONS`.
- **Fix (upstream):** Audit the 319 routes; migrate read paths to the RLS-respecting (anon/user-scoped) client wherever possible. For routes that must stay privileged, confirm each has an enforced account-scope guard and a `PRIVILEGED_DB_REASONS` entry. Add pgTAP negative tests proving cross-tenant reads fail.
- **Note:** Do not edit the mirror directly.

### P1-2. Contract validators are incomplete and duplicated
- **Locations:** `packages/pipeline_contracts/__init__.py` (Python validator), `packages/pipeline_contracts/typescript/` (TS validators, ~12 hand-coded functions).
- **Problem:** Both are hand-rolled (not `jsonschema`/`ajv`). They ignore `additionalProperties`, `min`/`max`, `pattern`, and `$ref`. Non-conforming payloads pass validation. The Python and TS implementations can silently diverge. (Note: `pnpm check:contracts` validates *drift/sync between mirrors*, not schema-constraint rigor — so its green status does not cover this.)
- **Fix:** Replace Python validator with `jsonschema` (Draft 2020-12) and TS with `ajv`, both compiling the same schema files in `packages/pipeline_contracts/schemas/`. Add negative-path tests: invalid enum, out-of-range, extra property, missing required, bad pattern — per schema.
- **Verify:** `pnpm check:contracts` green; new negative tests fail the old validators and pass the new ones.

### P1-3. campaign_factory `core.py` god-class (27k lines, 847 methods)
- **Location:** `python_packages/campaign_factory/.../core.py`
- **Problem:** Single `CampaignFactory` class, ~26,907 lines. Largest maintainability/onboarding risk in the repo. Drags Maintainability to 3/10.
- **Fix (incremental, behavior-preserving):** Extract by domain into mixins/modules under a `campaign_factory/core/` package — e.g. `db.py` (persistence), `audit.py` (ContentForge coordination), `export.py` (draft payloads), `orchestration.py` (batch/control-brain), `performance.py` (feedback loop). Keep `CampaignFactory` as a thin composition facade so callers don't break. Move tests alongside.
- **Constraint:** No behavior change. Each extraction is its own commit with the full test suite green.

### P1-4. reference_factory: doc/code drift on legacy providers + latent bug
- **Locations:**
  - Drift: `python_packages/reference_factory/AGENTS.md:8` says Grok is not active, but `grok_image` is the **default** `--variation-model`, and `analyze-/compile-prompts-with-grok-api` + Ollama (`--provider auto`) are live CLI subcommands (~600 lines).
  - Latent bug: `_caption_archetype` is duplicated with **divergent** logic at `patterns.py:469` and `public_metrics.py:383`; can raise `KeyError` in `_structure_notes`.
  - Dep gap: `google.genai` imported at `intake.py:524` but undeclared in `pyproject.toml`; `pydantic` used directly but only present transitively via fastapi.
- **Fix:** (a) Reconcile docs with reality — either re-document Grok/Ollama as active, or demote them in code to match docs. Decide intent. (b) Deduplicate `_caption_archetype` into one shared function; add a test covering the `KeyError` path. (c) Declare `google-genai` (optional extra) and `pydantic` explicitly in `pyproject`.
- **Verify:** 84 tests green; new caption-archetype test covers both call sites.

### P1-5. contentforge: large untested surface
- **Location:** `apps/contentforge` — `pipeline.js` (~800 lines), `app/api/.../similarity/route.js` (1827 lines), 27/29 API routes, `campaign-originality-audit.js`, ~2,255 LOC of Python forensics scripts.
- **Problem:** Core orchestration and most routes have no direct tests. FFmpeg integration tests **hard-fail** instead of skipping when the binary is absent. (Related to the now-fixed turbo env issue, but the skip-vs-fail behavior remains.)
- **Fix:** Add route-level tests (mock subprocess boundary) for `pipeline.js`, `buildPhase1Args`, and the API routes. Make FFmpeg-dependent tests **skip** (not fail) when `ffmpeg`/`ffprobe` are unavailable (probe-and-skip pattern). Add tests for the Python forensics branches.
- **Verify:** `npm test` passes with and without ffmpeg installed; coverage rises on `pipeline.js` and routes.

### P1-6. Stale / contradictory planning docs
- **Locations:** `MONOREPO_MIGRATION_MASTER_PLAN.md` (describes a *finished* migration as future "planned" phases), `AGENTS.md` (claims split repos are still the runtime — contradicts the monorepo reality).
- **Problem:** A new contributor (or agent) is actively misled. Documentation Hygiene scored 4/10.
- **Fix:** Archive `MONOREPO_MIGRATION_MASTER_PLAN.md` to `docs/archive/` with a header noting it's historical. Update `AGENTS.md` and root `README.md` to state the monorepo is canonical and the four tools live in `python_packages/` + `apps/`. Cross-check `CONSOLIDATION_STATUS.md` / `PIPELINE_STATE.md` are current (they are, per audit).
- **Verify:** No doc claims the migration is pending or that runtime tools are external repos.

### P1-7. Security scans are broad but non-blocking
- **Location:** `.github/workflows/security.yml` (and related).
- **Problem:** TruffleHog, Trivy, and dependency-review all run with `continue-on-error` / `--exit-code 0`. Only gitleaks + `scripts/security/secret-scan.sh` actually gate. Visibility without enforcement.
- **Fix:** Make Trivy (HIGH/CRITICAL) and dependency-review gating on PRs. Keep TruffleHog gating for verified secrets. Where false-positive noise is the reason for `continue-on-error`, add an explicit allowlist instead of disabling the gate.
- **Verify:** A PR introducing a known-vulnerable dep or a planted secret fails CI.

---

## P2 — Cleanup

### P2-1. Standalone test collection fails without workspace install (downgraded from P0)
- **Location:** `python_packages/campaign_factory` tests; root `conftest.py` / workspace install.
- **Status correction:** The combined Python pytest run **passes** in the configured workspace env (confirmed during PR #38 gates). The original audit agent saw `ModuleNotFoundError: pipeline_contracts` only because it ran the package *in isolation* without the workspace install. So this is **dev-ergonomics, not blocking** — corrected down from P0.
- **Problem:** A contributor who runs `pytest` inside `python_packages/campaign_factory` without first installing the workspace gets `ModuleNotFoundError: pipeline_contracts`.
- **Fix:** Make `packages/pipeline_contracts` resolvable standalone — editable install via `uv`/`pyproject` workspace dep, or a `conftest.py` `sys.path` shim. Document the one-time setup in README.
- **Verify:** Fresh clone → package-local `pytest` collects without a manual path hack.

### P2-2. Oversized modules (beyond campaign core.py)
- `python_packages/reference_factory/.../reference_intake.py` (2858 lines), `higgsfield_runner.py` (2060), `_run_pair` (~350-line branch monster).
- `python_packages/reel_factory`: `reel_gui.py`, `reel_pipeline.py`, `generate_prompts.py` (each 1.6k–2.5k lines); 90-file flat namespace.
- `apps/contentforge`: `similarity/route.js` (1827), `pipeline.js` (800).
- **Fix:** Decompose opportunistically when touching these files. Not a standalone task.

### P2-3. Legacy/experiment files in reel_factory
- Files: `old_new_reference_factory_experiment.py`, `grok_ab_experiment.py`, `tribev2_score_generated_panels.py` (~67KB combined).
- **Fix:** Delete if confirmed dead, or move to a clearly-marked `experiments/` dir excluded from packaging.

### P2-4. Broad exception swallowing
- **Location:** `python_packages/reel_factory` — 121 `except Exception` blocks that can mask failures. campaign_factory has ~20 TODO/legacy markers.
- **Fix:** Narrow exception types where the failure mode is known; log-and-reraise where currently silent.

### P2-5. Monorepo config nits
- `httpx2>0.28` in a Python dependency list — almost certainly a typo for `httpx`. Verify and fix.
- `repurposer` is physically nested inside `campaign_factory`, muddying the dependency model. Consider promoting to its own package or documenting the nesting.
- **Verify:** `pnpm check:contracts` and arch-guard scripts still pass.

### P2-6. Architecture-guard meta-tests never run in CI
- **Location:** `scripts/test-architecture-guards.sh` is not invoked by any workflow.
- **Fix:** Add a CI step that runs it. Add a boundary contract for `reel_factory` (currently a flat legacy `.py` dump with no import-linter contract).

### P2-7. contentforge: forensic heuristics are pseudo-rigorous
- **Location:** `apps/contentforge/.../forensics_check.py`
- **Problem:** The "Benford" check uses last-digit mod 10 (not leading digit); GOP-DFT/quality estimates are fragile. Numbers aren't trustworthy (non-blocking — advisory output).
- **Fix:** Either correct the Benford implementation (leading-digit distribution) or relabel these as heuristic/advisory in output so they aren't mistaken for rigorous forensics.
- **Minor:** `drawtext` filtergraph escaping gap (`,`/`;` unescaped); O(n²) re-embedding in cross-variant PDQ/SSCD loops.

### P2-8. Pillow deprecation (forward-compat)
- **Location:** `python_packages/reel_factory/.../grid_crop.py:125`, `overnight_grid_worker.py:237`.
- **Problem:** Deprecated Pillow `getdata` calls break on Pillow 14.
- **Fix:** Migrate to the supported API before bumping Pillow.

### P2-9. Dashboard type-safety erosion **[mirror→upstream]**
- 419 `any` usages + a `getSupabaseAny` deep-type escape hatch weaken compile-time guarantees. Address upstream in TD; tighten types incrementally.

---

## ContentForge is a content spoofer (intended — documented)

**Decision (owner-confirmed):** ContentForge is intentionally a content spoofer, not a quality auditor. It is explicitly engineered to **break perceptual hashes (PDQ/SSCD) to evade platform duplicate/similarity detection** and **rewrite capture metadata** (`creation_time`, `handler_name`, device-matched x264 params/filenames) so re-used content reads as an original device capture. The "forensics/readiness/similarity" checks score how convincing each spoof is, not content quality.

Docs updated to state this plainly (root `README.md`, `AGENTS.md`, `apps/contentforge/README.md`). No longer treated as a mismatch to resolve.

**Score taxonomy (matters for the constraints below):**
- **Spoof/evasion meters:** `sourceSimilarity`, `variantToVariantSimilarity`, `variationScore` — how well the variant defeats duplicate detection.
- **Output-quality guards:** `creativeQualityScore`, `readabilityScore`, `safeZoneScore` — perceptible quality of the delivered video. These are the **quality floor**.

**Constraints for any ContentForge work:**
1. **Quality floor is non-negotiable.** Spoof transforms (noise injection, recompression, crops, geometric warps, metadata rewrites) must **not worsen perceptible video quality**. Any change that lowers `creativeQualityScore`/`readabilityScore`/`safeZoneScore` for equivalent inputs, or visibly degrades output, is a regression — block it. Spoof strength may only increase by means that hold quality constant or improve it.
2. **Spoof improvement is allowed — but owner-directed.** The owner will direct spoof-capability work explicitly (planned, not now). Agents must not unilaterally extend/strengthen evasion outside an explicit owner instruction. When directed, constraint #1 still binds.
3. This is Terms-of-Service-evasion tooling; account-ban / takedown risk is the owner's accepted trade-off.

---

## Definition of done

- All P0 items resolved; their verify steps pass.
- `pnpm check:contracts` green.
- Each Python package: test suite collects and passes (README Quick Health Check commands).
- `apps/contentforge`: `npm test` passes with and without ffmpeg present.
- No planning doc contradicts the monorepo-is-canonical reality.
- Dashboard items routed upstream, not edited in the mirror.

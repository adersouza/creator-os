> ## ✅ STATUS: COMPLETE (2026-07-02)
> All items implemented, merged to main, and adversarially verified (PRs #323–#345, final fixes PR #340/#341). Zero fakes across four verification rounds. This plan is closed.

# Codex Master Run — Implement All Three Improvement Plans

**Paste the goal prompt below to Codex to run all three plans autonomously to completion.**
Author: Claude (Opus 4.8, 1M). Date: 2026-07-01.

---

**Codex: implement all three improvement plans on `main`, autonomously, to completion.**

Three self-contained master docs live in `docs/` on `main`. Each has its own **GOAL PROMPT**,
**Standing Constraints**, tiered items with file:line evidence + tests, dependency graph, and Status log.
Read all three before starting:

1. `docs/REEL_ENGINE_IMPROVEMENT_PLAN.md` — the learning loop (17 items; **0.1, 1.1–1.5, 2.1, 3.1 already
   merged** — only 2.2, 2.3, 2.4, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7 remain).
2. `docs/PIPELINE_HARDENING_PLAN.md` — video/audio quality, cost, publish, ingestion, throughput (21 items).
3. `docs/RELIABILITY_SECURITY_PLAN.md` — robustness, security, operator UI, contracts, DB, debt (23 items).

**The per-doc GOAL PROMPT + Standing Constraints in each file are authoritative** — obey them for every
item (one PR each, branch `codex/<slug>`, real tests, full CI green, merge, delete branch, tick the Status
box, then continue). The hard rules and stop-conditions are identical across all three.

**Global execution order (overrides per-doc order only for the emergency pass):**

- **Phase 1 — correctness/data-integrity first, across all docs, before anything else:**
  `RELIABILITY 0.1` (reel_outcomes NULL upsert crash), `RELIABILITY 0.2` (render_queue double-claim),
  `RELIABILITY 0.3` (contract validation silent no-op), `HARDENING 0.1` (distribution cadence double-book),
  then `RELIABILITY 1.1` (Higgsfield runner hang/silent-no-op) and `RELIABILITY 1.2` (LLM timeout/retry) —
  these two stop hung calls from burning paid generation.
- **Phase 2 — finish the learning-loop doc** (remaining items, top-down: 2.2 → 2.3 → 2.4 → 3.2 → 3.3 → 3.4
  → 3.5 → 3.6 → 3.7).
- **Phase 3 — the hardening doc**, top-down (skip 0.1, done in Phase 1).
- **Phase 4 — the reliability doc**, top-down (skip 0.1/0.2/0.3/1.1/1.2, done in Phase 1).

Within each phase, honor that doc's own dependency graph.

**Cross-doc coordination (do not duplicate or conflict):**
- `RELIABILITY 4.1` enforces the `recommendation_next_batch` contract; `REEL_ENGINE 3.4` unifies the
  `next_batch` schema. Do `REEL_ENGINE 3.4` first (Phase 2), then `RELIABILITY 4.1` validates the unified shape.
- `RELIABILITY 5.3` (hot-path indexes) and `REEL_ENGINE 3.5` (stable join keys) both touch the
  metrics↔outputs join. Do `REEL_ENGINE 3.5` first; `RELIABILITY 5.3` then only adds indexes, doesn't re-do
  the key.
- `HARDENING 5.1` (per-account cadence config) depends on `HARDENING 0.1` (done Phase 1) — fine.
- `RELIABILITY 6.3` (virality_select reward basis) depends on `REEL_ENGINE 1.2` (engagement-rate reward) —
  already merged, so 6.3 can use the shared helper directly.
- `RELIABILITY 2.1` (ContentForge API auth) and `RELIABILITY 3.4` (reel_gui onboarding/auth) **must agree on
  one auth model** — decide it once in 2.1, apply it in 3.4.

**Hard rules (from every doc — never violate, even to finish):** never publish/schedule/post or run paid/live
gen or ThreadsDashboard/Supabase export; never commit secrets or model binaries; never touch
`identity_references/` (biometric); never loosen the exposure gate or censor legal-adult captions; never
bypass/`xfail`/delete a failing test to go green — fix the code or STOP; never fake a checkbox. For DB items,
never drop/rename a column live code reads without migrating; if a backfill can't run safely headless, ship
forward-compatible code and STOP.

**STOP and ask the human** on any item that needs a product/policy decision (data-retention window, auth
model, which standalone CLIs to delete, cost thresholds), genuine correctness ambiguity, an unsatisfiable
prerequisite, or anything the Standing Constraints forbid. Surface specifics, pause, resume when answered.

**Done only when** all remaining boxes across all three Status logs are `[x]` and merged green. Do not stop
between items or between docs — continue automatically.

**Out of scope (human, not you):** actually posting reels, paid test runs, real credentials. Build it; the
human runs the flywheel.

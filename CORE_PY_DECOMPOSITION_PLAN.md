# core.py Decomposition Plan — the Campaign Factory god-class

**Audience:** Codex + owner. **Repo:** creator-os. **Target:** `python_packages/campaign_factory/campaign_factory/core.py` — single class `CampaignFactory`, **lines 623–26,760, ~831 methods**. This is the single biggest lever on the system score (caps Campaign Factory ~7.3 → 9; maint sub-score 4). It is also the **highest-risk** change in the codebase — this plan exists so it's executed with a net, not freehand.

---

## The crux finding (why this is tractable)

A read-only structural audit found the class is **near-stateless orchestration**. True instance state is **only two attributes**:

| Attribute | Refs | Role |
|-----------|------|------|
| `self.conn` | 377 | SQLite connection — the hub every cluster shares |
| `self.settings` | 23 | Config (paths/env) — used by a few clusters |

Everything else that *looks* like shared state (`self._creator_label`, `self._ratio`, …) is a **method call**, not an attribute. **There is no tangled mutable object graph.** Decomposition is therefore **grouping methods that share a DB connection** — not unwinding state. That's a fundamentally safer refactor than a typical god-class.

**Consequence — the target shape:** extract each cluster into its own module that takes `conn` (+ `settings` where needed). `CampaignFactory` becomes a **thin facade** that constructs the modules and **delegates** — its public method signatures stay identical, so **no caller changes**. The god-class shrinks to a composition root.

---

## Cluster map (≈26 modules)

### Tier 1 — lowest risk, extract FIRST (~35 methods, zero cross-cluster calls)
| Cluster | Methods | Lines | New module |
|---------|---------|-------|-----------|
| Graph nodes/edges | 7 | 633–816 | `graph.py` |
| Event pipeline / jobs | 9 | 828–1338 | `events.py` |
| Model/Campaign/Account upserts | 7 | 4206–4377 | `models.py` |
| Asset import | 2 | 4833–4997 | `asset_import.py` |

These depend only on `conn` + `settings`. No circular deps. They prove the pattern.

### Tier 2 — medium risk (~70 methods, manageable cycles via DI)
| Cluster | Methods | Lines | Module | Note |
|---------|---------|-------|--------|------|
| Creative planning | 13 | 890–1241 | `creative_planning.py` | depends on `events` |
| Reference management | 18 | 1142–25357 | `reference.py` | ↔ Audio cycle → inject scorer as callable |
| Caption family | 10 | 5090–25186 | `caption.py` | ↔ Performance cycle → inject scorer as callable |
| Distribution planning | 12 | 4402–21588 | `distribution.py` | called by Inventory + Asset import |
| Decision ledger | 15 | 13257–13619 | `decision_ledger.py` | reporting; isolated helpers |
| Exception management | 11 | 10392–13225 | `exceptions.py` | ↔ Recommendation cycle |
| Discoverability gates | 12 | 10163–12922 | `discoverability.py` | intake/gen/pre-render gates |

### Tier 3 — high risk, extract LAST (~450 methods, orchestration hubs + heavy helpers)
Account-autonomy/trust (15) · Inventory audit (53) · Factory metrics + TribeV2 A/B (45+20) · Audio management (52) · Story management (31) · Variant generation (24) · Account health (7) · Operator review (19) · **Performance analysis (24 — highest fan-in, 5+ caller clusters)** · Lifecycle tracking (23) · Publishing audit (9) · Creative-knowledge analytics (27) · Surface registration (27) · Winner expansion (13) · Carousel integrity (12) · Recommendation lifecycle (12).

> **Hidden region:** lines 10,100–23,400 (~424 methods, ~47% of the body) were scattered/unmapped — they contain 6 first-class domains (Creative-knowledge analytics, TribeV2 A/B, Surface registration, Decision ledger, Winner expansion, Carousel integrity). Surface these as their own modules; don't let them dissolve into Inventory/Factory by accident.

### Shared utilities → a service, not duplication
These are called everywhere (not state): `record_event` (40), `campaign_by_slug` (35), `graph_id_for` (35), `rendered_asset` (24), `ensure_graph_edge` (28). Extract into a `CoreServices`/`Repo` object holding `conn`, injected into every module. Don't copy them.

### Circular dependencies to break (confirmed)
| Cycle | Break with |
|-------|-----------|
| Performance ↔ Caption | inject a `PerformanceScorer` callable into `caption.py` |
| Recommendation ↔ Account | event/callback, not direct call |
| Audio ↔ Reference | inject `AudioScorer` callable into `reference.py` |
| Lifecycle ↔ Performance | Lifecycle reads Performance tables (unidirectional) — keep as read, no back-call |

---

## The non-negotiable safety net — characterization tests FIRST

**No extraction PR may land before its cluster is pinned by characterization tests.** core.py has no real test coverage today; a refactor without a behavior lock is how you silently corrupt the control brain.

- **PR 0 (before any extraction):** build a characterization harness — a seeded SQLite fixture + golden-output tests that call the *current* public methods and snapshot their returns/DB side-effects. Cover at minimum the Tier-1 + Tier-2 clusters' public entry points. These tests must pass **identically** before and after each extraction — that's the definition of done for every move below.
- Run the existing `pipeline_smoke` / `audio_smoke` / contract tests as additional guards.

### Implementation ledger

| Slice | Status | Verification notes |
|-------|--------|--------------------|
| PR 0 — characterization harness | Merged in PR #88 (`98a0530`) | Adds `python_packages/campaign_factory/tests/test_core_characterization.py`, pinning Tier 1 graph/events/jobs/models/asset-import behavior and representative Tier 2 planning/distribution/exception/discoverability/decision/caption behavior. The harness uses seeded SQLite state, normalized generated identifiers, golden payload assertions, and DB side-effect counts. Verified with focused characterization tests, full Campaign Factory pytest, contracts, architecture, artifact, integration, secret-scan, and repo test gates. No production code moves were included. |
| PR 1 — `CoreServices` extraction | Merged in PR #89 (`6d633ba`) | Extracts shared repository utilities into `campaign_factory.services.CoreServices` and keeps `CampaignFactory` as the public facade for `record_event`, `campaign_by_slug`, `graph_id_for`, `rendered_asset`, `ensure_graph_edge`, and the supporting `ensure_graph_node`. Verified with focused extraction facade tests, focused characterization tests, full Campaign Factory pytest (452 passed, 1 existing Starlette/httpx warning), `pnpm check:contracts`, `pnpm check:arch`, `pnpm check:arch:fixtures`, `pnpm check:artifacts`, `pnpm check:integration`, `pnpm security:secrets`, `pnpm test`, and `pnpm graphify:update` with ignored local graph output. |
| PR 2 — Graph repository extraction | Merged in PR #90 (`cbc79b2`) | Extracts graph node/edge/sync-state persistence into `campaign_factory.graph.GraphRepository`, composed by `CoreServices` while keeping `CampaignFactory` public graph methods unchanged. Verified with focused extraction facade tests, focused characterization tests, full Campaign Factory pytest (453 passed, 1 existing Starlette/httpx warning), `pnpm check:contracts`, `pnpm check:arch`, `pnpm check:arch:fixtures`, `pnpm check:artifacts`, `pnpm check:integration`, `pnpm security:secrets`, `pnpm test`, and `pnpm graphify:update` with ignored local graph output. |
| PR 3 — Event/job repository extraction | Merged in PR #92 (`450245a`) | Extracts activity-event and pipeline-job persistence into `campaign_factory.events.EventRepository`, composed by `CoreServices` while keeping `CampaignFactory` public event/job methods unchanged. Verified with focused extraction facade tests, focused characterization tests, full Campaign Factory pytest (454 passed, 1 existing Starlette/httpx warning), `pnpm check:contracts`, `pnpm check:arch`, `pnpm check:arch:fixtures`, `pnpm check:artifacts`, `pnpm check:integration`, `pnpm security:secrets`, `pnpm test`, and `pnpm graphify:update` with ignored local graph output. |
| PR 4 — Model/account repository extraction | Ready for PR on `codex/core-models-extraction` | Extracts model, campaign, account, and model-account-profile persistence into `campaign_factory.models.ModelRepository`, composed by `CoreServices` while keeping `CampaignFactory` public model/account methods unchanged. Verified with focused extraction facade tests, focused characterization tests, full Campaign Factory pytest (455 passed, 1 existing Starlette/httpx warning), `pnpm check:contracts`, `pnpm check:arch`, `pnpm check:arch:fixtures`, `pnpm check:artifacts`, `pnpm check:integration`, `pnpm security:secrets`, `pnpm test`, and `pnpm graphify:update` with ignored local graph output. |

---

## PR sequence (one cluster per PR; facade keeps the public API)

1. **PR 0 — characterization harness** (seeded fixture + golden tests for Tier 1+2 entry points). No code moves.
2. **PR 1 — `CoreServices` extraction**: move the 5 shared utilities into an injected service object; `CampaignFactory` holds one `self.services`. Pure plumbing, golden tests unchanged.
3. **PRs 2–5 — Tier 1** (`graph.py`, `events.py`, `models.py`, `asset_import.py`): one module each. `CampaignFactory` delegates. Golden tests green each time.
4. **PRs 6–12 — Tier 2** (creative_planning, reference, caption, distribution, decision_ledger, exceptions, discoverability), breaking the Audio/Performance cycles via injected callables as you go.
5. **PRs 13+ — Tier 3**, one cluster per PR, extracted as facades that compose Tier 1+2. Do **Performance, Lifecycle, Inventory, Audio last** (highest fan-in/helper density). Surface the 6 hidden-region domains explicitly.
6. **Final — `CampaignFactory` is a composition root**: constructs modules, delegates. Target: core.py drops from ~26.7k lines to a thin facade; each module is independently testable. **Campaign Factory maint 4→8, score 6.1→~8+.**

---

## Constraints

- **Public API is frozen.** Every `CampaignFactory.<method>` signature stays; callers (`adapters/`, CLI, stages) must not change. Facade delegates.
- **One cluster per PR**; characterization + golden tests green before and after; `pnpm check:contracts` green.
- **No behavior change** — this is pure structure. Any behavior fix is a *separate* PR, never bundled into an extraction.
- **No new logic in core.py** during this work (the standing constraint) — new modules only.
- creator-os `main` protected: feature branch → PR; required CI must pass.
- If a cluster won't extract cleanly under its characterization tests, **stop and report** — don't force it. Partial decomposition (Tier 1+2 done, Tier 3 staged) is still a large maint win.

---

## Honest scope

This is **~20+ PRs** and the riskiest track in the repo — but the near-stateless finding makes it mechanical rather than archaeological. It's the only thing that lifts Campaign Factory (the control brain, currently the system's lowest-scoring core component) past ~7.5. Sequence it **after** `TRACK9_RIGOR_PROMPT.md` PR 1 (contract codegen) so the contract layer is drift-proof first, and gate every move behind the characterization net.

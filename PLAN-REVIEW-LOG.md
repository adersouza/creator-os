# Plan Review Log: Close the Creator OS learning loop (audit steps 1+2+4)
Act 1 (grill) complete — plan locked with the user. MAX_ROUNDS=5.
Reviewer: codex-cli 0.144.0, model gpt-5.6-sol (xhigh). Note: CLI upgraded from 0.141.0 via npm (self-updater broken upstream for 0.144.0 assets); invoked as /opt/homebrew/bin/codex.

## Round 1 — VERDICT:REVISE
Findings (verified against code before revising):
1. **Sequencing / fail-open**: metric-history fetch fail-opens (threadsdash.py ~4153: RuntimeError → empty history + `metric_history_unavailable` warning, sync continues). Fix must land first; plan didn't order it as a prerequisite or address fail-open masking.
2. **Invented enforcement boundary**: plan assumed an "orchestrator draft creation" point that doesn't exist as named. Real lineage writers: campaign_factory/exports.py (+ account_planning.py, creative_planning.py, motion_edit_stage.py). Lineage contract already exists: packages/pipeline_contracts/schemas/generated_asset_lineage.v1.schema.json — conform, don't invent fields.
3. **metrics_eligible already exists** (campaign_factory/db.py:364 et al., INTEGER NOT NULL DEFAULT 0) — no new migration; plan implied a new flag.
4. **Forward-only not guaranteed**: readiness gate selects all historical metrics_eligible=1 snapshots (learning_readiness.py); needs explicit cutover, else historic posts leak into the 50-post gate.
5. **Idempotency ledger too coarse**: (post_id, snapshot_hour) alone can't handle partial fan-out failure; needs per-destination completion status. Reel intelligence_store has latest-snapshot-wins upsert semantics (metrics_store.py) that differ from append-only campaign snapshots — must be reconciled explicitly.
6. **Reference outcome contract**: import_prompt_outcomes (outcomes.py) expects a specific scalar-reward record shape; "compute rewardScore at read time" conflicts with fan-out needing a scalar at write time — must define when/how reward is stamped for reference records.
7. **Reinvented scoring**: canonical account-normalized scoring already exists — learning_score.py `account_normalized_decay_shrinkage.v1` (account median baseline + default prior + shrinkage). Plan proposed a new z-score formula; z-score degenerates at low n / zero variance; follower-based normalization moot (0/520 coverage).
8. **patterns.py collision**: `_performance_class` already uses rewardScore thresholds 1.05/0.85; label multipliers applied naively would corrupt performance classes. Must specify exact application point (cluster ranking weight only).
9. **reason_tags redundant**: review.py `label_reference` already accepts `tags` param — new field would create competing sources.

Resolution: PLAN.md revised to address all 9 (reuse existing schema/flag/scoring, explicit step 0 sequencing + fail-open reporting, cutover timestamp for forward-only, per-destination ledger, reward stamped at fan-out with scoringVersion for reference records, label weights confined to cluster ranking, dropped reason_tags).

## Round 2 — VERDICT:REVISE
Codex confirmed Round 1 items resolved (ordering, metrics_eligible reuse, cutover, per-destination tracking, tags reuse). New findings:
1. **Fallback rows poison the gate**: on history failure/omission, `_threadsdash_performance_rows` substitutes the ordinary post row, imported as metrics-eligible (threadsdash.py:4153, :4662); readiness derives 1h/24h from `snapshot_at - published_at` (learning_readiness.py:15) so fallback rows masquerade as history. Need per-post history provenance; exclude fallback rows from readiness AND fan-out.
2. **Campaign snapshots are upsert, not append-only**: `(post_id, snapshot_at)` conflict updates all metric fields (threadsdash.py:4246); a corrected snapshot updates Campaign while `done` ledger rows suppress Reel/Reference refresh. Ledger needs source-hash change detection that reopens destinations.
3. **Ledger key contradictory + too coarse**: §3 said snapshot_hour, §4 put scoring_version in the key; Campaign keys by exact `snapshot_at` (db.py:448) — two snapshots in one hour collide.
4. **Canonical scalar undefined**: `account_normalized_decay_shrinkage.v1` is a version string returned by `learning_summary` (learning_score.py:115), not a per-snapshot callable. Consumers diverge: Reference classifies rewardScore at 1.05/0.85 (patterns.py:1180); Reel winner-DNA uses unrelated log `winner_score` (intelligence_store.py:339, winner_dna.py:925). Must name exact callable + every consuming read path.
5. **scoring_version bump insufficient**: account baselines are recomputed medians of current latest snapshots (learning_score.py:17) — new posts silently shift older normalized rewards; Reference stores one overwrite-in-place scalar per prompt (reference db.py:304). Need frozen baseline with provenance or cohort invalidation.
6. **Lineage v1 too weak for Reference fan-out**: schema requires only source/generation/review objects, `referenceId`/`promptId` optional (schema:6), but `import_prompt_outcomes` requires one (outcomes.py:23). Enforcing via v2 requires updating campaign_draft_payload.v1.schema.json:324 hard-reference + mirror regeneration.
7. **Wrong label-weight application point**: cluster ranking lives in learning.py (:234, :481), not patterns.py; `_pattern_cards` (learning.py:151) doesn't load review_labels — data wiring missing; planned test couldn't prove anything.
8. **Completion/ordering unsafe**: `import_prompt_outcomes` overwrites unconditionally with import-time timestamp (outcomes.py:63) — retried stale snapshot can overwrite newer outcome; missing matches and Reel write failures are soft-skips (outcomes.py:84, metrics_store.py:587) that would be marked done. Need monotonic latest-snapshot handling + done-only-after-verified-write + soft-skip tests.

Resolution: Rev 3 — history provenance flag excluding fallback rows from gate+fan-out; ledger keyed (post_id, snapshot_at, destination) + source_hash reopen; named per-snapshot callable extracted from existing baseline/shrinkage pieces with explicit consumer map (Reel winner_score untouched, raw-metrics-only feed); frozen baseline provenance stamped per outcome + monotonic source_snapshot_at guard on Reference overwrites; lineage v2 with required identifiers + draft-payload contract ref bump + mirror regen; label weights wired in learning.py with review_labels join; soft-skips treated as pending-not-done.

## Round 3 (Rev 3 reviewed) — VERDICT:REVISE, 7 findings → Rev 4
1. Reference overwrite-in-place scalar loses per-post evidence; reference_id-only match broadcasts. → CONFIRMED (db.py:304 UNIQUE(reference_id,target_tool,model_profile); outcomes.py:50). Fixed: new `prompt_post_outcomes` (prompt_id, post_id) table; prompt-level outcome_* becomes derived aggregate; prompt_id required for writes.
2. Unledgered Reel refresh in sync script bypasses cutover/ledger. → CONFIRMED (sync_threadsdash_performance.py:88 runs build_refresh_command; metrics_store.py:555 selects all metrics_eligible=1). Fixed: standalone refresh removed; ingestion only via ledger-controlled fan-out.
3. Cutover/provenance filtering only on gate+fan-out; Campaign scoring/baselines read all eligible rows. → CONFIRMED (performance_summary.py:34). Fixed: single `learning_eligible` predicate governs gate, scoring, baselines, fan-out.
4. source_hash covered only raw metrics; attribution corrections wouldn't reopen rows. → Fixed: hash = complete normalized fan-out input, per destination.
5. pending/done state model can't express superseded writes or retry caps. → Fixed: added `superseded`, `failed_capped`, `attempt_count` (cap default 5).
6. Scalar definition ambiguous (0–100 score vs relative reward vs shrunk). → CONFIRMED (learning_score.py:147ff). Fixed: exact equation = unshrunk relative_reward = snapshot_reward / max(1e-6, baseline); parity test vs learning_summary internals.
7. In-place mutation of pinned campaign_draft_payload.v1 breaking; audio_id legitimately null at export. → CONFIRMED (validator.py:18; threadsdash.py:3037). Fixed: draft_payload v2 + dual validation; audio_intent ID required instead, platform audio_id late-bound.

## Round 4 (Rev 4 reviewed) — VERDICT:REVISE, 6 findings → Rev 5
1. TS validator hard-codes v1 (typescript/index.ts:12,1253) and ThreadsDashboard draftIngest.ts:439 consumes it; schema regen won't update it. → CONFIRMED. Fixed: explicit rollout sequencing — dual-accept in Python + TS validators, deploy ThreadsDashboard, THEN flip exports to v2.
2. Eligible→ineligible snapshots leave orphaned destination facts. → Fixed: bridge scans all previously-ledgered rows regardless of current eligibility; new terminal `retracted` status; per-post outcome deleted + aggregate recomputed; Reel row removed; dedicated test.
3. Reel "latest-wins" is only the MAX(snapshot_at) source query; reel_outcomes upsert overwrites unconditionally, no source snapshot stored (intelligence_store.py:70, metrics_store.py:649). → CONFIRMED. Fixed: additive `source_snapshot_at` column + monotonic guard mirroring Reference; older ⇒ superseded.
4. Reference read paths denormalized: outcomes reach ranking only via analyze_patterns embedding into pattern_json; build_learning_system doesn't refresh by default (learning.py:33). → CONFIRMED. Fixed: bridge triggers targeted pattern refresh for references whose aggregates changed; e2e test.
5. Predicate coverage incomplete: recommendations.py:400, account_memory.py:41, performance_summary.py:180 (asset planning), creative_knowledge.py:1211, winner_expansion.py:403 still query metrics_eligible=1 directly. → CONFIRMED (spot-checked recommendations + account_memory). Fixed: consumers enumerated in plan; shared SQL helper; per-consumer tests.
6. audio_intent.v1 defines no ID; _build_audio_intent emits none (threadsdash.py:2689). → CONFIRMED. Fixed: lineage v2 requires deterministic `audio_intent_fingerprint` (canonical-JSON SHA-256 computed at export); no mutation of audio_intent.v1.

## Round 5 (Rev 5 reviewed, FINAL round) — VERDICT:REVISE, 5 findings → Rev 6
1. §1 allowed referenceId-only lineage while §3 requires resolved promptId; multi-prompt references (db.py:319) unresolvable → drafts count toward readiness with stranded fan-out. → CONFIRMED. Fixed: promptId required; referenceId demoted to cross-check; post-cutover v1-lineage posts fenced from learning_eligible.
2. audio_intent_fingerprint can't be computed at exports.py:203 — final intent built later in adapter. → CONFIRMED. Fixed: fingerprint stamped after _build_audio_intent per final draft; gate validates there.
3. Ledger stored no destination identity → identity-changing corrections orphan old facts; retraction unsafe when snapshots collapse; publish_metrics upsert unguarded (metrics_store.py:700). → CONFIRMED. Fixed: destination_record_id column; transactional replace; retraction recomputes from newest remaining eligible snapshot; publish_metrics ledger-controlled.
4. Consumer list still incomplete: recommendations.py:2095/:2775 measurement path, variant_lineage.py:1129 → creator_os_recommendations.py:128. → CONFIRMED. Fixed: added to predicate list + tests.
5. v2 hard-required variantId but normal path has enable_variation=False (threadsdash.py:63) and nullable variant_id (db.py:177) → base exports would fail gate. → CONFIRMED. Fixed: variantId conditional on variation stage; base identity = rendered-asset ID.

MAX_ROUNDS=5 reached without APPROVED. Rev 6 addresses all Round 5 findings; verdict on Rev 6 not yet obtained. Escalated to user for decision (extra confirmation round vs accept Rev 6).

## Round 6 (Rev 6 reviewed, user-authorized confirmation round) — VERDICT:REVISE, 3 residuals → Rev 7
Scope-limited to Round-5 fix verification. Fixes (2) fingerprint-in-adapter and (4) consumer predicate list confirmed correct. Residuals:
1. Predicate/prose contradiction: PLAN prose required lineage-v2 for learning but authoritative `learning_eligible` definition omitted the clause → post-cutover v1 record would pass. CONFIRMED (grep). Fixed: `lineage_v2_valid=1` added to both Python callable and shared SQL fragment.
2. `publish_metrics` keyed by filename (metrics_store.py:704) while `outcome_id` encodes account+posted_at (metrics_store.py:652) → distinct outcomes collapse onto one filename row; ledger stored only `outcome_id`. CONFIRMED. Fixed: ledger records outcome_id + filename identity per destination write; collapsed row recomputed from newest remaining eligible outcome on retraction, deleted if none.
3. `variantId` not wired to variation path: adapter sources `variant_id` from base-asset publishability, stores `variantAssignment.variant_asset_id` separately (threadsdash.py:3142, variation_stage.py:238). CONFIRMED. Fixed: lineage variantId stamped from assignment before final v2 validation; positive varied-path test + wrong-source failure test added.

Rev 7 written. Verdict on Rev 7 not obtained (user-authorized extra round exhausted).
## PLAN-SCHEDULER Review Log

## Phase 0 — Render/export identity

- Added real frame-sampled pHash and exact byte fingerprint generation in Reel Factory.
- Render lineage is now emitted for every completed render; approved export enriches legacy lineage before export.
- Source-family identity is carried from reference/learning lineage when present.
- Added deterministic image pHash and lineage carry-forward tests.

## Phase 1 — Fail-closed assignment eligibility

- Added one Campaign Factory evaluator and persisted `origin_account_id`.
- Gated `distribution_plans`, `asset_account_assignments`, `asset_inventory_reservations`, and Reel-ledger promotion writes.
- Mirrored missing-identity/origin behavior in Reel Factory posting-ledger UX.
- Added readiness/review blocked counts and explicit `missing_identity_metadata` reasons.

## Phase 2 — Contract and parity

- Added canonical `campaign_factory.assignment_eligibility.v1` schema, example, Python validator, CLI artifact export, and Reel Factory artifact consumption.
- Artifact retains `auto_posting: false` and exposes all decision inputs/matches.
- No Reel Factory import of Campaign Factory was introduced.

## Phase 3 — Trial intent and graduation

- Added `trial_group_id` across distribution, draft metadata, and handoff manifest.
- Added manual same-account idempotent graduation with unique `trial_post_id` mapping and no scheduled time.
- Added 1-hour/24-hour observation storage and nightly ranking report command.
- Added `main_reels_per_day=1` and `trial_reels_per_day=2` defaults in `account_content_requirements`.

## Phase 4 — ThreadsDashboard timing ownership

- Implemented in the isolated ThreadsDashboard branch `codex/plan-scheduler-v3`.
- Account-local timezones and configurable/derived base slots replace global New York timing.
- Deterministic jitter is bounded to plus or minus 20 minutes, stays on the local date, and respects account minimum gaps.
- Spring-forward and fall-back tests cover `America/New_York`; schedule-approved drafts remain timing-locked.

## Phase 5 — Promotion truth

- Added constrained `promotions` and typed append-only `promotion_events` tables.
- Promotion validates lineage fingerprint and removed file-hash fallback computation.
- Added idempotent legacy backfill, fingerprint reconciliation, stable CSV output, constrained identity authority, and latest-event status reads.
- Added concurrent unique-constraint proof with exactly one winner.

## Second audit — locked-plan closure

- Removed the remaining trial-graduation fallback to `rendered_assets.content_hash`; graduation now requires the lineage-v2 `contentFingerprint` before creating a regular plan or promotion.
- Made assignment eligibility evaluation side-effect-free and persist `origin_account_id` only after the assignment, reservation, distribution plan, or promotion bridge write succeeds.
- Made the Campaign Factory eligibility artifact authoritative when Reel Factory receives it; the local rule mirror is now compatibility fallback only. Added allowed and blocked parity tests.
- Added `account_group_id` to promotion state, indexed the exact identity/window lookup on the promotion store, and stopped rescanning campaign ledger rows for cross-account reuse.
- Expanded typed promotion events with rendered asset, fingerprint, account, slot, and reason identity columns. Current status is the latest event for the exact identity key.
- Converted live uniqueness races into savepoint-backed typed skips and typed rejection events instead of transaction-wide failures.
- Made legacy backfill quarantine duplicate identities with a typed rejection and stable report row instead of raising `IntegrityError`.

## Verification and landing

- Creator OS `make verify` passes against the isolated ThreadsDashboard consumer: contracts, Ruff, formatting, mypy, architecture, artifact checks, both Next builds, 187 JavaScript/TypeScript tests, and 1,469 Python tests. All 153 ContentForge tests pass; its existing lint baseline remains 23 warnings and 0 errors.
- Campaign Factory passes 709 tests, including fail-closed eligibility, promotion idempotency, migration quarantine, reconciliation, and the exactly-one-winner concurrency proof. Reel Factory passes all 579 tests with the optional vision/AI dependencies installed.
- ThreadsDashboard passes 5,195 tests (1 skipped, 3 todo), typecheck, Biome lint, compatibility checks, contract parity, migration replay lint, and its production build/bundle budgets.
- Unblocked the existing Tailwind 4 build mismatch in both Creator OS Next apps by switching their PostCSS integration to `@tailwindcss/postcss`.
- Creator OS landing is published as PR #378 from `codex/plan-scheduler-v3`;
  the combined audit verification tree is `codex/audit1-handoff`. No merge or
  deployment is performed by this plan.
- No production deployment or autoposter state change is authorized by this plan.

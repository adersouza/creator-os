# Pipeline Hardening & Output-Quality Plan — Codex Master Doc

**Owner:** Emerson. **Author:** Claude (Opus 4.8, 1M). **Date:** 2026-07-01.
**Product:** autonomous/semi-autonomous short-form content engine. Owner supplies REFERENCE
material → system analyzes → generates SIMILAR reels with the owner's trained Higgsfield Soul →
QC (anatomy/exposure/identity/anti-copy) → rank → render captions → schedule to social accounts
via ThreadsDashboard. **Optimize VIEWS + ENGAGEMENT. Bottleneck = content QUALITY + VOLUME.**

**Scope of THIS doc:** the parts of the pipeline OUTSIDE the learning loop —
video-animation output quality, audio mux, cost accounting, publish/schedule reliability,
ingestion integrity, and throughput. These are complementary to (and share the same standing
constraints as) `docs/REEL_ENGINE_IMPROVEMENT_PLAN.md` (the learning-loop doc, 17 items). Do that
one FIRST if both are open; this doc has one item (0.1) that is a correctness bug worth pulling
forward regardless. No item here depends on the learning-loop doc, and vice-versa, except where noted.

## GOAL PROMPT (paste this to Codex to run autonomously to completion)

> **Goal:** implement EVERY item in this document (`docs/PIPELINE_HARDENING_PLAN.md`), in the listed
> dependency order, one PR each, until the entire Status log at the bottom is checked `[x]` and merged.
> **Do not stop after one item — continue to the next automatically.** You are done only when all items
> are merged green.
>
> **Loop, per item, top-down:**
> 1. Read the item + the Standing Constraints. Implement it on branch `codex/<slug>` as described.
> 2. "Done properly" = ALL per-PR verification passes (`ruff format` + `ruff check`, full `pytest` green,
>    `make verify`, `pnpm security:secrets`, empty `git ls-files models secrets.toml`), the item's own
>    tests are real (not stubbed/skipped/`xfail`), CI is fully green, and the PR is merged. Delete the branch.
> 3. Tick the item's box in the Status log (commit that update), then immediately start the next item.
> 4. Respect the dependency graph — never start an item before its prerequisites are merged.
>
> **Hard rules (never violate, even to "finish"):**
> - Never publish, schedule, post, or run paid/live generation, `--schedule-mode live`, `--enable-live`,
>   `--enable-paid-generation`, `export-threadsdash`, or `--allow-unbudgeted-local-test`. All work is
>   code + tests only. Where an item touches the publish path, the change is to the CODE that runs when a
>   human later triggers it — you never trigger it.
> - Never commit secrets (`project_data/secrets.toml`) or model binaries; never touch `identity_references/`;
>   never loosen the exposure gate or censor legal-adult (18/19) captions.
> - Never bypass, weaken, `xfail`, or delete a failing test to make CI green. If a test legitimately fails,
>   fix the code. If the whole suite can't pass, STOP.
> - Never fake completion. A box is `[x]` only when truly merged green with real tests.
>
> **When to STOP and ask the human (do not guess):** a product decision (which timezone per account, what
> daily cap, cost thresholds), genuine code ambiguity where getting it wrong risks correctness, an
> unsatisfiable prerequisite, or anything the Standing Constraints forbid. Surface specifics, pause, resume
> when answered.
>
> **Out of scope for you (human action, not a code item):** actually posting reels, spinning up paid
> generation to test, or supplying real credentials. Build the hardening; the human runs the pipeline.

## How Codex uses this doc

- Work **top-down in the listed order** — items are sequenced by dependency + severity.
- **One PR per item.** Branch `codex/<slug>`, one focused commit, open PR, verify CI green, merge, delete branch.
- Re-read the **Standing Constraints** before every item.
- If an item is bigger than expected, ship the smaller correct version and note what's deferred in the PR. Never paper over with a suppression/skip.
- After each merge, update the "Status" checkbox in a follow-up commit.

## Standing Constraints (apply to EVERY item)

- **NEVER** publish, schedule, or post. **NEVER** run paid or live generation, `--schedule-mode live`,
  `--enable-live`, `--enable-paid-generation`, `export-threadsdash`, or `--allow-unbudgeted-local-test`.
  All work is code + tests only.
- **NEVER** commit secrets (`project_data/secrets.toml`) or model binaries — models are fetched via
  `fetch_models.py` (CI `hygiene` + `secret-scan` block committed runtime-artifact binaries).
- Don't touch `identity_references/` (gitignored face embeddings).
- Exposure ceiling: implied/covered only. Do NOT loosen the exposure gate. Do NOT censor legal-adult
  (18/19) captions.
- Keep `python_packages/reel_factory/tests/fixtures/broad_exception_allowlist.txt` line-synced if any
  `except Exception` handler shifts (`test_exception_boundaries.py` checks exact `file:function:line`).
- Leave the unrelated pre-existing Knip edits (`package.json`, `pnpm-lock.yaml`) untouched.
- **Higgsfield model facts (verified via `higgsfield model get kling3_0`):** `kling3_0` exposes params
  `mode {std,pro,4k}` (default `std`), `duration` (int), `--start-image`, `--end-image`, aspect ratio.
  It has **NO seed and NO negative-prompt** param — do not add code that passes those to Kling.
- **Per-PR verification (all must pass before merge):**
  - `uv run --package reel-factory ruff format python_packages/reel_factory/`
  - `uv run --package reel-factory ruff check python_packages/reel_factory/`
  - `uv run --directory python_packages/reel_factory python -m pytest -q`  (currently **432 passing**; add your new tests)
  - For campaign_factory items: `uv run --directory python_packages/campaign_factory python -m pytest -q` too
  - `make verify`
  - `pnpm security:secrets`
  - `git ls-files python_packages/reel_factory/models project_data/secrets.toml`  → must be empty
  - Commit trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

## The core problem (why this order)

The learning loop is being wired up separately. But the reel that loop selects still has to be
GOOD when it renders and RELIABLE when it schedules — and today: the animated video is rendered at
Kling's lowest quality mode and never re-QC'd (only the still is gated, so morphing/limb-warp ships
unseen); paid spend is invisible to the ledger and the "daily budget" is really a per-run cap; the
distribution planner forgets prior runs and can double-book an account; and there's no operator
visibility when an export silently dies (the exact shape of the June-2026 publishing incident).
Fix the one correctness bug first, then the highest quality-per-post levers, then reliability, then
throughput.

---

## TIER 0 — Correctness bug (do first)

### 0.1 Distribution planner double-books accounts across runs  ·  CRITICAL · M · [ ]
**Branch:** `codex/distribution-cadence-hydrate`
**Why:** `distribution.py:392-393` initialises `account_day_counts = {}` and `account_last_time = {}`
fresh every planner run. The ≥1/day cap (`:604`) and the <4h spacing gate (`:608-609`) therefore only
see slots planned **within the current run** — they never query already-planned/scheduled rows. Re-running
the planner (or a second campaign touching the same account) double-books the same account/day and violates
the min-gap. This is a publishing-correctness bug, same class as the prior "publishing" incident.
**Do:** before the planning loop, hydrate `account_day_counts` and `account_last_time` from existing
`distribution_plans` / scheduled rows for the target accounts over the planning window, so the caps span
runs. Read-only hydration — no publish/schedule side effects.
**Tests:** a second planner run over the same account+date respects the ≥1/day cap (no double-book); an
existing scheduled post at T forces the next slot ≥ min-gap after T; empty history behaves exactly as today.

---

## TIER 1 — Video output quality (highest quality-per-post levers)

### 1.1 Render Kling at `pro` (or `4k` for hero), not the default `std`  ·  HIGH · S · [x]
**Branch:** `codex/kling-quality-mode`
**Why:** `build_video_cmd` (`generate_assets.py:150-182`) never emits `--mode`, so every animated reel
uses Kling's lowest `std` mode. `higgsfield model get kling3_0` shows `mode {std,pro,4k}` default `std`.
This is the single biggest visual-fidelity knob and it's left at the floor.
**Do:** add a `mode` param to `build_video_cmd` (default `"pro"`), thread it from plan/config, and pass
`--mode`. Allow `"4k"` opt-in for hero clips. Keep it config-driven, not hardcoded, so cost/quality is tunable.
**Cost note:** higher mode may cost more credits — do NOT run paid gen to test; unit-test the command
construction only.
**Tests:** `build_video_cmd` emits `--mode pro` by default; `4k`/`std` override honored; no `--mode` when
explicitly disabled (back-comfort).

### 1.2 QC the animated VIDEO, not just the still  ·  HIGH · M · [x]
**Branch:** `codex/video-output-qc`
**Why:** `run_generated_image_qc` (`generate_assets.py:1098-1102`) filters to `image`/`variation_*` keys;
the downloaded `video` (`:1023-1024`) is never anatomy/exposure/identity checked. Defects Kling introduces
*during* animation (limb-warp, morphing, extra fingers) pass because only the pre-animation still was gated.
**Do:** sample N frames (e.g. 4-5 evenly spaced) from the rendered mp4 and run `anatomy_qc.assess_image_qc`
per frame; block promotion on the worst frame (fail-closed, matching the still gate). Reuse the existing
frame-extraction helper used by copy-detection (`sscd_video.py` already samples 5 frames — share it).
**Tests:** a clip whose sampled frame fails anatomy/exposure is rejected; a clean clip passes; no-provider →
fail-closed reject (same contract as the still gate). Use the injectable `vision_call` for no-spend tests.

### 1.3 Multi-frame identity check on video (not one frame at t=0.5s)  ·  HIGH · S-M · [x]
**Branch:** `codex/identity-multiframe-video`
**Why:** `identity_verification._media_frame_for_embedding` (`identity_verification.py:149-156`) extracts a
single frame at `-ss 0.500` and embeds only that. Identity drift later in the clip (face rotating off the
Soul over 5s) is invisible. Compounds 1.2.
**Do:** for video inputs, embed 3-5 frames spread across the clip and gate on the **minimum** cosine
similarity vs the Soul reference set (worst frame decides), not one early frame. Keep still-image behavior
unchanged.
**Tests:** a clip that drifts on a late frame fails on the min even though t=0.5s passes; a consistent clip
passes; still-image path unchanged; threshold stays 0.42.

### 1.4 Audio mux quality: hook offset + loudness + use the ranked track  ·  MED · S-M · [x]
**Branch:** `codex/audio-mux-quality`
**Why (three small, related bugs in the mux path):**
- `audio_mux.mux_audio` (`audio_mux.py:129-156`) feeds the track from 0:00 (`-stream_loop -1 … -shortest`),
  so the recognizable drop (often 10-30s in) never plays. `_audio_meta` already loads a sidecar.
- No loudness normalization — static `volume=0.82` + fades (`:123-127`), so track levels vary wildly.
- `audio_provider.select_audio` ranks/chooses a trending track, but `mux_root` (`reel_pipeline.py:2771`)
  independently re-rolls a random local file via `audio_mux.select_audio(seed=…)` — the ranked selection's
  `track_id`/path is discarded at mux time. (Distinct from learning-doc item 3.7, which is the rng weighting
  *inside* the provider.)
**Do:** (a) read an optional `hook_offset` from the track sidecar and add `-ss <offset>` on the audio input;
(b) add `loudnorm=I=-14:TP=-1.5:LRA=11` to the `-af` chain (IG/TikTok ≈ -14 LUFS); (c) thread the provider's
resolved local path into `mux_root` so the ranked track is what actually gets muxed.
**Tests:** offset present → `-ss` in cmd; absent → no `-ss`; `loudnorm` always in `-af`; `mux_root` uses the
provider-selected path when given, falls back to random only when none supplied.

### 1.5 Optional: `--end-image` bookend + reference-matched duration  ·  MED · M · [x]
**Branch:** `codex/kling-endframe-duration`
**Why:** `build_video_cmd` only ever passes `--start-image` (`:169-172`); `--end-image` is supported and
bookending the motion sharply cuts identity/pose drift and enables controlled camera moves. Separately,
`plan.video_duration` defaults to 5 everywhere (`:81`) though the analyzer already computes the reference's
duration — watch-time varies with length.
**Do:** (a) optionally pass an accepted still as `--end-image` for locked motion; (b) derive clip duration
from the reference (capped to a sane max) instead of the hardcoded 5.
**Tests:** end-image threaded when provided; duration derived from reference, capped; defaults unchanged when
neither supplied.

---

## TIER 2 — Cost accounting (spend is currently blind)

### 2.1 Record paid Higgsfield/Kling spend to the cost ledger  ·  HIGH · M · [x]
**Branch:** `codex/wire-ai-cost-ledger`
**Why:** `campaign_factory/cost_tracker.py` has an `ai_cost_events` table + `record_ai_cost` with
`higgsfield`/`kling` pricing slots, but neither `reel_factory/generate_assets.py` nor
`reference_factory/higgsfield_runner.py` ever call it (grep returns nothing). `higgsfield_runner.py:1576-1582`
computes per-manifest `actualCredits` but writes them only to lineage JSON. Spend on the two priciest providers
never reaches the ledger.
**Do:** call `record_ai_cost` after each successful gen in `generate_assets` / `higgsfield_runner`, using the
`actualCredits` when available (fall back to the estimate). Read-only w.r.t. providers — just records what
already happened.
**Tests:** a gen records one `ai_cost_events` row with provider + credits; a failed gen records nothing (or a
zero-cost failed row, your call — test whichever you implement).
**Note:** `PROVIDER_PRICING` is a hardcoded June-2026 estimate and `actualCredits`→USD conversion doesn't exist
— leave a `TODO` to reconcile credits→USD from the Higgsfield API; don't block this PR on it.

### 2.2 Make the "daily budget" an actual daily sum, not a per-run cap  ·  HIGH · S-M · [x]
**Branch:** `codex/preflight-daily-sum`
**Why:** `higgsfield_cost_preflight.py:147-152` compares a single run's `estimated_cost_usd` against
`HIGGSFIELD_DAILY_BUDGET_USD` with no persisted daily total — so N runs each under budget never trip the cap.
The "daily" budget doesn't accumulate. Depends on 2.1 (needs recorded events to sum).
**Do:** have preflight query today's `SUM(estimated_cost_usd)` (or credits) from `ai_cost_events` for the
account/day and compare `running_total + this_run` against the daily budget; block if it would exceed. Keep
the existing per-run and minimum-balance checks.
**Tests:** two runs that individually pass but together exceed the daily budget → second is blocked; under-budget
day passes; empty ledger behaves as today.

---

## TIER 3 — Publish reliability + operator visibility (prior-incident class)

### 3.1 Surface stuck/failed exports (no more "publishing died, nobody noticed")  ·  HIGH · M · [x]
**Branch:** `codex/export-failure-visibility`
**Why:** three blind spots let a dead export go unnoticed:
- Nothing ever SELECTs jobs in `'running'`/`'queued'` — a killed export sticks forever (`events.py:172` writes
  the state, no reader; `started_at` exists at `db.py:560`).
- `unresolved_failed_jobs` marks a failure resolved on ANY later same-`jobType` success
  (`campaign_overview.py:203`), so a failed `threadsdash_export` for asset X vanishes when asset Y succeeds —
  corrupting `campaign_health.v1` `failedJobs`.
- A failed export writes no `threadsdash_exports` row (INSERT only on success, `threadsdash.py:890-901`; the
  `except` at `:962-972` fails the job + re-raises) — that table shows only successes.
**Do:** (a) add a `jobs --status running,failed` view (current `jobs` CLI at `cli.py:3079` requires
`--campaign` and has no status filter); (b) scope failure-resolution to campaign+asset identity, not bare
`jobType`; (c) write a `failed`-status `threadsdash_exports` row in the except block before re-raising.
**Tests:** a failed export leaves a `failed` row + shows in `jobs --status failed`; a later unrelated success
does NOT resolve it; a running job that never completes is listable.

### 3.2 Fail loud on silent live→dry-run / mode downgrade  ·  HIGH · S · [x]
**Branch:** `codex/publish-no-silent-downgrade`
**Why:** `cli.py:1568-1569`: `dry_run = args.dry_run or not (supabase_url and service_role_key)` — a
misconfigured/absent credential silently coerces a live export to dry-run, exit 0, no warning. And
`_normalize_schedule_mode` (`distribution.py:49-51`) coerces any unknown/empty mode to `"draft"`, which gates
publishing (`threadsdash.py:762`). Both are the flag-fragility shape of the prior incident.
**Do:** if the operator asked for a live run (`not args.dry_run`) but creds are absent, RAISE with an actionable
message instead of coercing to dry-run. If a schedule mode is non-empty but unrecognized, raise rather than
silently defaulting to `draft` (empty → documented default is fine).
**Tests:** live-requested + missing creds → raises (not a silent exit 0); unknown mode → raises; empty mode →
default; valid live path unchanged.
**Constraint reminder:** this changes the CODE that runs when the human triggers a live export — you still never
trigger one.

### 3.3 Make the reel_factory ThreadsDashboard queue endpoint idempotent + guarded  ·  HIGH · M · [ ]
**Branch:** `codex/reelgui-queue-idempotent`
**Why:** `reel_gui.py:741` sets `post_id = sha256(f"{dest}:{time.time()}")` (time-seeded) and `:761` appends to
`queue.jsonl` on every call — re-queuing the same output makes a fresh id + duplicate line, with no dedup on
source path/fingerprint and no creator-identity check. Endpoint `/api/threadsdashboard/queue` (`reel_gui.py:2702`)
bypasses every guarantee the posting_ledger enforces.
**Do:** derive `post_id` from the content fingerprint (or source path), upsert instead of blind-append, and route
the enqueue through (or reuse) the posting_ledger dedup + creator-identity guard so the operator-facing queue
has the same guarantees as `assign_approved_reels`.
**Tests:** enqueuing the same output twice yields one entry (idempotent); different content → distinct ids; an
identity-mismatched item is rejected the same way the ledger rejects it.

### 3.4 Slot assignment: no global one-way cursor  ·  MED-HIGH · M · [x]
**Branch:** `codex/ledger-slot-matching`
**Why:** `posting_ledger.py:309/356-358` use a single monotonic `slot_idx` across all items; a conflict advances
the cursor and those slots are never revisited for later items, and the terminal-conflict branch (`:371-382`)
consumes a slot with nothing assigned. Items arrive in encode order (`export_approved.py:55`
`ORDER BY v.encoded_at`), so a mid-list conflict can starve later items of otherwise-open slots.
**Do:** match items↔slots without a global cursor — per-item scan of all still-open slots — and never advance
past a slot on a non-assigning conflict. (The "feed best-ranked reels first" half overlaps orchestrator item 3.2
in the other doc; this PR is only the cursor-correctness fix.)
**Tests:** an early-item conflict doesn't burn a slot the next item could use; terminal conflict leaves all slots
available; happy path assigns identically to today.

### 3.5 Retry Supabase media upload like the ingest POST already does  ·  MED · M · [x]
**Branch:** `codex/supabase-upload-retry`
**Why:** the only retry loop is the ingest POST (`threadsdash.py:1875-1917`); `SupabaseRestClient._open_json_or_empty`
(`:5505-5511`) has no retry and raises on any HTTP error, and `_upload_media_for_dashboard_ingest` re-raises as a
fatal export block (`:1535-1541`). The largest, most failure-prone step (binary upload) is the least resilient —
one transient 5xx aborts the whole export.
**Do:** wrap `SupabaseRestClient` requests (at minimum media upload) in the same bounded backoff used for the
ingest POST. Also upsert the media row on `storage_path` (`threadsdash.py:2109` is a plain insert; a crash between
the dedup select `:2061-2085` and insert leaves a duplicate row — storage upload itself is already `upsert=True`).
**Tests:** a transient 5xx then success → upload succeeds after retry (mock transport); a permanent error still
raises; media row upsert doesn't duplicate on re-run.

---

## TIER 4 — Ingestion + data integrity

### 4.1 Quarantined captions must stay out on re-scan  ·  HIGH · S · [x]
**Branch:** `codex/quarantine-blocks-reentry`
**Why:** `bad_caption_quarantine.json` is written by `build_inventory` (`caption_intake.py:412-424`) but
`_add_candidate` (`:681-729`) only checks live-bank `existing` keys — never the quarantined hashes. A caption
quarantined for unsafe/nonsense/generated_seed re-enters on the next `scan-local`/`ocr`/`import-external`.
Integrity gap on the #1 engagement lever.
**Do:** load quarantine hashes into the `existing`/block set consulted by `_existing_keys`/`_add_candidate` so a
quarantined caption is never re-admitted.
**Tests:** a quarantined caption is not re-added on re-scan; a normal new caption still adds; un-quarantining
(removing from the file) re-admits.

### 4.2 Content-hash reference dedup + capture source metrics at import  ·  MED · S-M · [x]
**Branch:** `codex/reference-dedup-and-metrics`
**Why:** `scan.py:39` keys references on `sha1(path|size)` and `:58` leaves `content_hash = NULL`, though
`identity.py:19` has a working `content_hash()` that's never used — byte-identical reels at two paths become two
references, inflating the learning set with dupes. Separately, `reel_url_import.py:22-35` runs yt-dlp with no
`--write-info-json`, so the reference's views/likes/upload-date at import time are never recorded (sidecar at
`reel_gui.py:1511-1521` stores only url/stem/path) — data the recency/rate ranking work presupposes.
**Do:** (a) populate `content_hash` in `scan_source` and dedup on it (or a reconcile pass); (b) add
`--write-info-json` to the yt-dlp import, parse `view_count`/`like_count`/`upload_date` into the sidecar +
reference record.
**Tests:** two paths, same bytes → one reference; info-json parsed into the sidecar; missing metrics degrade
gracefully (nulls, no crash).

### 4.3 yt-dlp import resilience: retry + duplicate-URL guard  ·  MED · M · [x]
**Branch:** `codex/ytdlp-retry-dedup`
**Why:** `reel_url_import.py:66-71` runs yt-dlp once — any transient failure or IG/TikTok 429/block raises
immediately, no backoff. No duplicate-URL detection (dedup is only by dest filename/`stem`, `:60-61`), so the same
URL under a new stem re-downloads. (Cookie support for private/age-gated reels is a nice-to-have; note it, don't
block on it.)
**Do:** add bounded retry with backoff on nonzero exit; check the URL against existing sidecars before downloading
and short-circuit if already imported. Collapse the dead identical webm→mp4 branch (`:87-93`) to one `shutil.move`
while you're here.
**Tests:** transient failure then success → retried; already-imported URL → skipped, no re-download; distinct URL →
downloads.

### 4.4 Aggregated failure / dead-letter view for failed gens  ·  MED · M · [x]
**Branch:** `codex/gen-dead-letter`
**Why:** cost-preflight blocks (`generate_assets.py:832-848`) and gen failures (`_record_generation_failure`,
`:866-925`) each write a single lineage JSON with `status: *_blocked/failed`; there's no aggregated surface
listing failed/blocked gens across a batch and no resume of a partially-failed batch. Only ~3 of ~50 reel_factory
modules import `logging`.
**Do:** append failure/block records to one `failed_generations.jsonl` (append-only) and add a small
`queue_admin`/CLI view that lists them for retry/resume. Read-only reporting — no auto-retry of paid gen.
**Tests:** a blocked gen appends one dead-letter record; the view lists it; a successful gen appends nothing.

### 4.5 Decide policy on generated inventory/quarantine files  ·  LOW · S · [x]
**Branch:** `codex/caption-artifact-policy`
**Why:** `caption_source_inventory_20260629.{json,csv,md}`, `stacey_caption_adaptations.json`,
`bad_caption_quarantine.json` are untracked and not gitignored — dated inventory scratch accumulates per run with
no history, and quarantine/adaptation decisions (a real decision record) don't reach teammates on pull.
**Do:** gitignore the dated inventory scratch (`caption_source_inventory_*.{json,csv,md}`), and commit
`bad_caption_quarantine.json` + `stacey_caption_adaptations.json` as decision records (or persist those decisions
to the DB — pick one, note which).
**STOP-and-ask:** if unsure whether these belong in git vs the DB, ask the human — it's a policy call.

---

## TIER 5 — Throughput knobs (volume bottleneck)

### 5.1 Per-account cap + spacing from config, not hardcoded literals  ·  MED · M · [ ]
**Branch:** `codex/per-account-cadence-config`
**Why:** `distribution.py:604/608-609` hardcode ≥1/day and a 4h gap, ignoring DB
`account_content_requirements.max_per_day`/`min_gap_hours` (`db.py:733-734`) and `account_health.py:832-873`'s
computed `maxPostsPerDay`/`minimumGapHours` (used only for a health gate, never fed into the slot picker;
`min_gap_hours` is read nowhere). On the ledger side `SLOT_TYPES` hardcodes exactly 3 posts/day/account
(`posting_ledger.py:22`). Volume is capped by a literal, not the per-account config that already exists.
**Do:** pass the per-account `max_per_day` + `min_gap_hours` into `next_valid_distribution_slot`; make the ledger
`SLOT_TYPES`/`DEFAULT_SLOT_TIMES` config-driven per account. Depends on 0.1 (same cadence code path — do 0.1 first).
**Tests:** an account configured for 5/day gets 5 slots; a 2h-gap account spaces at 2h; missing config → current
defaults.

### 5.2 Per-account timezone (stop assuming America/New_York)  ·  MED · M · [ ]
**Branch:** `codex/per-account-timezone`
**Why:** `distribution.py:557-558` posts at fixed hours `[10,14,18]` in a fixed `ZoneInfo("America/New_York")` for
every creator (datetimes are correctly tz-aware — no naive bug, just one zone); ledger `DEFAULT_SLOT_TIMES` is
`10/15/20` with no tz at all (`posting_ledger.py:34`). Wrong-timezone posting misses the audience's peak.
**Do:** look up a per-account timezone (add to account config; default to the current NY if unset) and localize slot
times to it.
**Tests:** an account in `America/Los_Angeles` gets slots in PT; unset → NY default; tz-aware output preserved.
**STOP-and-ask:** where the per-account timezone should be stored if there's no obvious existing field.

### 5.3 Best-time-to-post (design item — scope before building)  ·  LOW · L/design · [ ]
**Branch:** `codex/best-time-to-post`
**Why:** no `best_time`/`peak_hour`/`by_hour` logic exists; slot hours are hardcoded despite retention/views being
tracked per post. Honest caveat: dispatch timing is delegated to ThreadsDashboard by design
(`threadsdash.py:299-302`), so best-time may not belong here at all.
**Do:** FIRST write a short design note in the PR: does best-time belong in the planner or in ThreadsDashboard? If
planner: derive peak hours per account from historical `reel_outcomes` by hour-of-day (engagement-rate weighted,
reuse the learning doc's 1.2 rate helper if merged) and pick slot hours from the top buckets with a sane floor.
**STOP-and-ask:** confirm ownership (planner vs ThreadsDashboard) before implementing.

---

## Dependency / sequence summary

```
0.1 cadence hydrate ───────────────► 5.1 per-account cap (same code path)
2.1 record spend ──────────────────► 2.2 daily-sum budget
1.2 video QC ──┬─ (independent of) ─ 1.3 multiframe identity
               └─ 1.1 mode, 1.4 audio, 1.5 endframe all independent
3.1 export visibility, 3.2 no-downgrade, 3.3 idempotent queue, 3.4 slot cursor,
    3.5 upload retry — all independent of each other
4.1 quarantine, 4.2 dedup+metrics, 4.3 ytdlp retry, 4.4 dead-letter, 4.5 policy — independent
5.1 depends on 0.1 ; 5.3 depends on a scoping decision (and ideally learning-doc 1.2)
```

**Recommended first cut:** 0.1 (correctness) → 1.1/1.2/1.3 (quality-per-post) → 2.1/2.2 (cost sanity) →
3.x (reliability) → 4.x (integrity) → 5.x (throughput). Only 2.2→2.1 and 5.1→0.1 are hard-ordered.

## Status log
- [x] 0.1 distribution cadence hydrate (double-book fix) — fast branch
- [x] 1.1 Kling pro/4k mode — `build_video_cmd` now emits `--mode pro` by default, honors `4k`, and supports explicit disabled mode; video dry-run tests passed.
- [x] 1.2 video output QC — downloaded videos now sample frames and run anatomy/exposure QC fail-closed; focused content-trust tests passed.
- [x] 1.3 multi-frame identity on video — video identity now checks multiple sampled frames and gates on the minimum similarity; content-trust tests passed.
- [x] 1.4 audio mux quality (hook offset + loudnorm + ranked track) — mux command now honors hook offsets, applies loudnorm, and accepts provider-selected local audio paths; focused audio mux tests passed.
- [x] 1.5 end-image bookend + reference duration — Kling commands now support `--end-image`; CLI derives duration from video references with a configurable cap and keeps default fallback; video dry-run tests passed.
- [x] 2.1 record AI spend to ledger — Reel Factory and Reference Factory successful Higgsfield/Kling calls now write idempotent cost ledger events with raw credit metadata; focused tests passed.
- [x] 2.2 daily-sum budget cap — Higgsfield preflight now sums today's `ai_cost_events` before applying the daily cap; focused tests passed.
- [x] 3.1 export failure/stuck visibility — jobs can be filtered by status, failed export attempts write failure manifests/rows, and failed-job resolution is scoped by asset identity; focused tests passed.
- [x] 3.2 no silent live→dry-run downgrade — live CLI export without credentials now fails loud and unknown schedule modes raise; focused tests passed.
- [ ] 3.3 idempotent + guarded reel_gui queue
- [x] 3.4 slot assignment cursor fix — assignment now scans open slots without consuming them on non-assignment conflicts; posting-ledger regression tests passed.
- [x] 3.5 supabase upload retry + media upsert — Supabase REST calls now retry transient failures and media rows upsert by storage path; focused tests passed.
- [x] 4.1 quarantine blocks re-entry — caption intake now treats bad-caption quarantine hashes/text as blocked existing keys; focused tests passed.
- [x] 4.2 content-hash dedup + import metrics — reference scan dedupes by SHA-256 content hash and reel URL import captures yt-dlp info-json metrics; focused tests passed.
- [x] 4.3 ytdlp retry + duplicate-URL guard — URL imports retry transient failures and skip URLs already recorded by import sidecars; focused tests passed.
- [x] 4.4 failed-gen dead-letter view — blocked/failed generation paths append `failed_generations.jsonl`, with a read-only `failed-generations` CLI mode; focused tests passed.
- [x] 4.5 caption artifact git policy — dated inventory scratch is gitignored/untracked; quarantine and Stacey adaptation decision records remain tracked.
- [ ] 5.1 per-account cap/spacing from config
- [ ] 5.2 per-account timezone
- [ ] 5.3 best-time-to-post (design first)

## Verified-fine (do NOT "fix" — audited and correct)
- Aspect ratio: pipeline forces `9:16` + 1080×1920 (`generate_assets.py:80,156`, `still_to_reel.py:23-24`) despite Kling's 16:9 default. No bug.
- Video copy-detection is genuinely multi-frame (`sscd_video.py`, max-similarity verdict).
- Motion prompts are multi-frame-derived via `analyze_reference` (`reference_analyzer.py:278-289`).
- Export **writer** is fail-closed: missing ingest URL/secret, publishability/manifest/live blockers all RAISE (`threadsdash.py:769-808,1861-1868`); legacy raw-Supabase writes off by default is healthy. The residual risk lives only in items 3.1/3.2.
- Ingest POST retries 408/409/425/429/5xx + timeout with backoff + idempotency key, then reconciles by post-key (`threadsdash.py:1766-1922`).
- posting_ledger transition state machine enforces ordered/terminal transitions + audio/lineage gates (`posting_ledger.py:998-1023`).

## Dropped after verification (false positives — do NOT chase)
- Kling seed control / negative-prompt — `kling3_0` exposes neither param.
- `reel_motion_prompt.py`'s hardcoded scene types — dead code (no live `.py` importer; only `.md`/`pyproject` refs).

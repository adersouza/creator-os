# Gap Closure Plan — close the verified partials from the three improvement docs

> ## GOAL PROMPT (for Codex)
>
> You are working in the Creator OS monorepo. An adversarial verification pass (2026-07-02) audited
> every `[x]` item in `docs/REEL_ENGINE_IMPROVEMENT_PLAN.md`, `docs/PIPELINE_HARDENING_PLAN.md`, and
> `docs/RELIABILITY_SECURITY_PLAN.md` against the actual code on `main`. 49/61 items were fully
> verified. 12 were PARTIAL — the core claim is real but one edge of a multi-part item was skipped.
> This doc is the complete list of those remaining edges. Do ALL 12 items on **one branch**
> (`codex/gap-closure-fast`) as **one PR** — speed over item-level granularity. Implement in the
> listed dependency order, one commit per item (so the history is still bisectable), but do NOT
> stop for per-item PRs, per-item CI waits, or per-item review.
>
> Process:
> 1. Create `codex/gap-closure-fast` off latest `main`.
> 2. Implement every item's Do section in dependency order, one commit each. Read the cited
>    file:line first — line numbers are from 2026-07-02 `main` (a4b9b342) and may have drifted.
> 3. Write the named tests as you go, but you may defer running the full suites until the end.
> 4. When ALL items are implemented: run the full test suite for every touched package plus the
>    focused tests named per item, fix everything, tick all Status-log boxes with a one-line
>    summary each, then open ONE PR and get CI green.
> 5. Final review happens once, after merge, as a separate adversarial verification pass (not
>    yours) — so never fake a checkbox; every claim will be re-checked against the code.
>
> Standing constraints (NEVER violate):
> - Never run paid generation, live scheduling, or publishing: no `--enable-paid-generation`,
>   `--enable-live`, `--schedule-mode live`, `export-threadsdash`, `attest-publishability`,
>   no `--allow-unbudgeted-local-test`.
> - Never commit secrets (`project_data/secrets.toml` stays gitignored), model binaries, or
>   anything under `identity_references/`.
> - Never fake completion. A box is `[x]` only when truly merged green with real tests.
> - Keep `broad_exception_allowlist.txt` line-synced if you touch listed files.

---

## Why this doc exists

The 2026-07-02 verification (3 adversarial agents, ~250 focused tests, all green) found **zero fake
items** but 12 partials. The pattern was consistent: multi-part items where the headline landed and
one edge got skipped. These edges are individually small (S–M) but several sit on the paid-spend
path or block the visibility the original items promised.

Explicitly **out of scope** (known, deliberate):
- REEL_ENGINE 2.1 semantic winner-DNA fields (subjectAction/wardrobe/hookType) stay heuristic on the
  free path — filling them requires the paid Gemini/VLM analysis, which needs owner authorization
  per run. Not a code gap.
- The `distribution.py` campaign-planner fallback slots hardcoding America/New_York — status log for
  HARDENING 5.2 only claimed the ledger side; revisit only if the fallback planner path is used for
  real scheduling.

---

## Tier 0 — paid-spend path (do first)

### 0.1 Harden reel_factory `download_result` (timeout + size + verify)  ·  HIGH · S-M · [x]

**Status:** `download_result` now streams with timeout, minimum-size/type checks, temp-file cleanup, and atomic replace; focused truncated/timeout tests pass.

**Branch:** `codex/reel-download-verify`

**Why:** RELIABILITY 1.1 hardened the reference_factory downloads but skipped the reel_factory
half. `python_packages/reel_factory/generate_assets.py:840-843` `download_result` still uses raw
`urllib.request.urlretrieve` — no timeout, no size verification — on ~5 live paid call sites.
`MIN_RESULT_BYTES = 1` catches only zero-byte files. A hung or truncated download after a paid
Kling/Soul call = money spent, corrupt/absent asset reported as success.

**Do:**
- Replace `urlretrieve` with the same pattern reference_factory uses (`higgsfield_runner.py:2715-2719`):
  `urlopen` with an explicit timeout (60s), stream to a temp file, then atomic rename.
- Verify the download: raise a meaningful minimum size (images ≥ 10 KB, videos ≥ 100 KB — make
  them module constants), and check Content-Type is image/* or video/* when the server provides it.
- On failure: raise (fail-closed) so the caller's existing failure path (dead-letter jsonl,
  cost-ledger notes) fires; never mark the asset generated.
- Cover every call site of `download_result` in `generate_assets.py`.

**Tests:** truncated-response and timeout simulations via a local `http.server` thread or mocked
`urlopen`; assert failure raises and no asset file persists. Extend
`tests/test_content_trust_hardening.py`.

### 0.2 Render-pack: async job + idempotency (finish RELIABILITY 3.1/3.2)  ·  HIGH · M · [x]

**Status:** Render-pack defaults to queued idempotent jobs with sync fallback; focused async dedupe and sync tests pass.

**Branch:** `codex/render-pack-async`

**Why:** The async-job infrastructure exists (`reel_gui.py:221-257`, status endpoint `:281-287`)
and 4 paid handlers use it, but render-pack was skipped: still a fully blocking ~900s POST
(`reel_gui.py:2640-2687`) with **no idempotency key and no client disable** (`static/app.js:2136`).
Browser timeout mid-render = work lost, no status; double-click = double work.

**Do:**
- Route the render-pack handler through the existing job queue (same pattern as the 4 converted
  handlers at `reel_gui.py:2045,2163,2270,2344`): enqueue, return job id, poll via the existing
  status endpoint.
- Add the idempotency key + in-flight dedupe (reuse `ASSET_IDEMPOTENCY` at `reel_gui.py:150,226-231`)
  and the client-side disable-until-settled pattern from `app.js:653-664,690-705`.
- Make async the DEFAULT for all paid/long handlers, keeping the legacy sync path only behind an
  explicit `sync=1` query param for tests/scripts. (Closes the "async is opt-in" gap from 3.1.)

**Tests:** duplicate render-pack click → one job; poll reaches terminal state; sync fallback still
works. Extend the existing no-spend job tests.

### 0.3 Ranked audio track actually reaches the mux by default  ·  HIGH · M · [x]

**Status:** Mux selection now honors manual override, ranked local provider tracks, then random fallback, with chosen track sidecars; focused audio tests pass.

**Branch:** `codex/ranked-audio-to-mux`

**Why:** HARDENING 1.4c built the plumbing (`audio_mux.py:250-266` accepts
`selected_audio_path`; `reel_pipeline.py:2774-2778` threads it) but nothing feeds it except a
manual `--audio-path` flag (`reel_pipeline.py:3105`). The original bug — ranker picks a track,
mux random-rolls a different one — persists in the default path. This throws away the
rank-weighted trending selection built in REEL_ENGINE 3.7.

**Do:**
- In the default pipeline path, call `audio_provider.select_audio` (the rank-weighted chooser,
  `audio_provider.py:224,283,291`) and pass the winning track's local path as
  `selected_audio_path` to the mux.
- `--audio-path` keeps highest precedence (manual override), then ranked selection, then the
  existing random fallback ONLY if the provider returns nothing.
- Record the chosen `track_id` in the output sidecar/manifest so winner-DNA audio attribution
  (already built) sees the truth.

**Tests:** default run muxes the provider-selected track (assert path equality); manual flag still
overrides; provider-empty falls back. Extend `tests/test_audio_mux.py` /
`tests/test_audio_provider.py`.

### 0.4 Ledger image spend when the paired video fails; budget fail-closed  ·  MED · S · [ ]

**Branch:** `codex/spend-edge-cases`

**Why (two small spend leaks found in verification):**
- A reference_factory image+video pair whose video fails (`video_failed`) never records the image
  spend to the cost ledger — undercounts real spend.
- `higgsfield_cost_preflight.py:126-144`: a `sqlite3.Error` reading today's spend coalesces to
  $0 — the daily cap silently fail-opens exactly when the ledger is broken.

**Do:**
- Record the image-cost ledger event as soon as the image succeeds, independent of the video's
  fate (the ledger is already idempotent, so this is safe).
- On `sqlite3.Error` in the daily-sum read: fail CLOSED for paid runs (block with a clear
  "cost ledger unreadable" error); allow an explicit `--budget-override-ledger-error` escape hatch.

**Tests:** video-fails-after-image → image event exists; corrupted-DB preflight → paid run blocked,
override flag unblocks. Extend `tests/test_content_trust_hardening.py`.

---

## Tier 1 — visibility + data integrity

### 1.1 Cross-campaign stuck/failed-job discovery (finish HARDENING 3.1a)  ·  HIGH · S · [ ]

**Branch:** `codex/jobs-all-campaigns`

**Why:** `jobs --status failed` exists but `--campaign` is still `required=True`
(`campaign_factory` `cli.py:1267`) — you cannot ask "is anything stuck ANYWHERE?", which was the
entire point of the item ("publishing died, nobody noticed").

**Do:**
- Make `--campaign` optional; when omitted, scan all campaigns and include a campaign column in the
  output. Add `--stuck-hours N` (default 24) to flag jobs pending longer than N hours.
- Surface the same all-campaigns counts in the reel_gui health summary (`reel_gui.py:1281-1312`)
  so the dashboard shows stuck exports without a CLI visit.

**Tests:** multi-campaign fixture, one stuck job → discovered without `--campaign`; stuck-hours
threshold respected.

### 1.2 One shared sqlite opener everywhere (finish RELIABILITY 5.1)  ·  MED-HIGH · S-M · [ ]

**Branch:** `codex/sqlite-opener-sweep`

**Why:** The 30s+WAL+busy_timeout helper exists (`metrics_store.py:33-38`) but ~11 openers on
shared DBs bypass it: bare 5s `sqlite3.connect` in `embedding_index.py:18`, `winner_dna.py:41`,
`readiness_check.py:151`, `reference_analyzer.py:323,362`, `export_approved.py:29`,
`caption_bank.py:724`, `generate_assets.py:681`; WAL missing at `metrics_store.py:457`;
timeout-only at `intelligence_store.py:60`, `campaign_store.py:123`, `posting_ledger.py:150`.
Under the new orchestrator + job queue these run concurrently — mixed journal modes and short
timeouts = `database is locked` under exactly the load the pipeline now generates.

**Do:**
- Promote the opener to a tiny shared module (one function; `packages/pipeline_contracts` already
  ships cross-package code, or a `_db.py` per package if import direction forbids it — pick the
  smallest correct home) and route every listed opener through it.
- Read-only openers may use the same helper with `mode=ro` URI — do not leave them on bare connect.
- Add a repo test that greps for `sqlite3.connect(` outside the helper(s) and fails on new
  offenders (allowlist the helper files).

**Tests:** the grep-guard test; concurrent reader/writer smoke test on one shared DB (two threads,
no `database is locked`).

### 1.3 Kill the leading-wildcard filename LIKE-join (finish RELIABILITY 5.3)  ·  MED · M · [ ]

**Branch:** `codex/filename-join-key`

**Why:** The headline join the index item promised to fix is still the primary lookup:
`LIKE '%/' || filename` at `campaign_factory` `manifest.py:446` and `metrics_store.py:109,246,998`.
The `variations` table has no filename column, so the scan is unindexable as-is. Also
`reel_factory/generate_assets.py:681-690` still runs cost-table DDL per insert.

**Do:**
- Add a `filename` (basename) column to the `variations` table via the existing generic migration
  path (`reference_factory/db.py:340-398` pattern / declared-schema diff), backfill from the
  existing path column, index it.
- Convert the four LIKE call sites to exact `filename = ?` with the LIKE kept only as a legacy
  fallback when the exact match returns nothing.
- Move `generate_assets.py` cost-table DDL to a once-per-connection guard (same fix already applied
  in campaign_factory `cost_tracker.py:120-124`).

**Tests:** legacy DB (no column) migrates + backfills; exact-match hit skips LIKE (assert via query
plan or call spy); joins return identical rows pre/post on a fixture.

### 1.4 Enforce the four reference_factory contracts (finish RELIABILITY 4.1)  ·  MED-HIGH · M · [ ]

**Branch:** `codex/reference-contract-enforcement`

**Why:** 6/11 contracts now raise at producer write boundaries, but all four reference_factory
ones the spec required are still validated by nobody: `pattern_card`, `video_analysis`,
`higgsfield_soul_image_prompt`, `kling_3_video_prompt` (plus optional
`recommendation_accuracy_report`, `repurposing_plan`).

**Do:**
- At each producer write site in reference_factory, validate through `pipeline_contracts.validator`
  and raise on failure (fail-closed), mirroring the pattern at `still_to_reel.py:352`.
- Fix any latent producer/schema drift the new enforcement exposes (that's the point).
- Optional pair (`recommendation_accuracy_report`, `repurposing_plan`): enforce if the producers
  are live; if a producer is dead code, delete the schema instead and note it in the PR.

**Tests:** valid payload passes; one mutated required field raises; per contract.

### 1.5 Import metrics reach the DB reference record (finish HARDENING 4.2b)  ·  MED · S · [ ]

**Branch:** `codex/import-metrics-db`

**Why:** yt-dlp info-json metrics (views/likes/etc. of the source reel) land in the sidecar only
(`reel_gui.py:1753-1763`); the `campaign_references` record has no metrics columns. Reference
ranking/recency work reads the DB, so source-performance signal is invisible to it.

**Do:**
- Add `source_views`, `source_likes`, `source_comments`, `source_posted_at` columns (generic
  migration path) to the reference record; populate at import time from the parsed info-json;
  backfill from existing sidecars where present.

**Tests:** import with info-json populates columns; sidecar backfill; missing metrics → NULLs, no
crash.

---

## Tier 2 — operator polish (batch into one or two PRs)

### 2.1 Fix the double-click launcher 401 (finish RELIABILITY 3.4a)  ·  MED · S · [ ]

**Branch:** `codex/launcher-onboarding`

**Why:** `make dev-reel` exports the loopback-auth env (`Makefile:22`) but the Finder
`Launch reel factory.command` doesn't — fresh checkout, double-click, every request 401s with no
hint (`local_api_auth.py:44-47`).

**Do:** make the `.command` launcher set the same explicit `ALLOW_INSECURE_LOCAL` + loopback bind
that `make dev-reel` sets, printing a one-line notice that dev auth-bypass is active and how to set
a real token. Do NOT weaken `local_api_auth.py` defaults.

**Tests:** shellcheck/bats-style check that the launcher exports the vars; existing node/python auth
tests unchanged.

### 2.2 ContentForge review: real cost tile + loading skeleton (finish RELIABILITY 3.5)  ·  LOW · S · [ ]

**Branch:** `codex/cf-review-polish-2`

**Why:** `ResultsGrid.jsx:379` ships a hardcoded `$0` Cost tile (worse than no tile — it asserts a
falsehood about paid spend), and the grid renders nothing during scan (no skeleton).

**Do:** feed the tile from the cost ledger via the existing summary/health API (or drop the tile if
the run has no ledger events — never show a made-up number); add the loading skeleton the original
item specced.

**Tests:** tile shows ledger-derived value / hides when absent; skeleton renders during pending
fetch. Extend the contentforge node tests.

### 2.3 Cadence hydration window honors `min_gap_hours` (edge from HARDENING 0.1)  ·  LOW-MED · S · [ ]

**Branch:** `codex/hydration-window`

**Why:** `distribution.py:608-609` hydrates persisted slots within a hardcoded ±4h buffer; an
account configured with `min_gap_hours > 4` can be double-booked at the window edge.

**Do:** derive the hydration window from the max configured `min_gap_hours` across active accounts
(floor 4h), instead of the literal.

**Tests:** account with 6h gap + persisted slot 5h away → new slot rejected.

---

## Dependency order (commit order on the single branch)

```
0.1 → 0.2 → 0.3 → 0.4        (spend path, sequential — same files)
1.1                           (independent)
1.2 → 1.3                     (opener sweep before join/migration work touches the same DBs)
1.4                           (independent)
1.5                           (after 1.3 if migration helpers move; else independent)
2.1, 2.2, 2.3                 (independent, any time)
```

The per-item **Branch:** lines above are legacy from the one-PR-per-item format — ignore them;
everything goes on `codex/gap-closure-fast`. Use them as commit-message prefixes instead
(e.g. `reel-download-verify: ...`).

## Status log

- [x] 0.1 reel_factory download verify — shared download_result now uses timeouted streaming, content-type/min-size checks, atomic rename, and no partial files; focused truncated/timeout tests passed.
- [x] 0.2 render-pack async + idempotency — render-pack now enqueues by default with deterministic idempotency, keeps sync behind sync=1, and the client polls/disables through the existing job helper; focused async/sync tests and JS syntax check passed.
- [ ] 0.3 ranked audio reaches mux by default (+ track_id recorded for attribution)
- [ ] 0.4 spend edge cases: image-on-video-fail ledgers; budget preflight fail-closed on ledger error
- [ ] 1.1 cross-campaign stuck-job discovery (`--campaign` optional, `--stuck-hours`, health view)
- [ ] 1.2 shared sqlite opener sweep + grep-guard test
- [ ] 1.3 filename join key (column + backfill + index, exact-first) + once-per-connection cost DDL
- [ ] 1.4 reference_factory contract enforcement (pattern_card, video_analysis, both prompt contracts)
- [ ] 1.5 import metrics to reference record (columns + sidecar backfill)
- [ ] 2.1 launcher onboarding fix (explicit dev-auth env in `.command`)
- [ ] 2.2 CF cost tile from ledger + loading skeleton
- [ ] 2.3 hydration window honors max `min_gap_hours`

## Verified-fine in the 2026-07-02 pass (do not re-litigate)

All other claims in the three source docs held up under adversarial verification: ON CONFLICT
keyed on `outcome_id`, rowcount-guarded render claims, full contentforge API auth coverage
(30/30 routes in matcher), persisted-slot cadence hydration, fail-closed video QC, min-similarity
multi-frame identity, idempotent cost ledger + cross-run daily sum, SystemExit on live-mode
credential downgrade, real Thompson bandit, biometric redaction/erasure, quarantine re-entry
blocking, per-account timezone in `planned_at`, schema auto-migration, dead-code deletion with
`deprecated_generators.py` preserved.

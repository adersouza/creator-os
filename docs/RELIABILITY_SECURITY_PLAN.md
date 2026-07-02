# Reliability, Security & Integrity Plan — Codex Master Doc

**Owner:** Emerson. **Author:** Claude (Opus 4.8, 1M). **Date:** 2026-07-01.
**Product:** autonomous/semi-autonomous short-form content engine (see the two sibling docs).
**Scope of THIS doc:** the plumbing that makes the pipeline TRUSTWORTHY — external-call robustness
(Higgsfield job lifecycle + LLM calls), DB/concurrency correctness, cross-package contract enforcement,
security/privacy, operator-UI reliability, and dead-code/debt cleanup. Complements:
- `docs/REEL_ENGINE_IMPROVEMENT_PLAN.md` — the learning loop (17 items).
- `docs/PIPELINE_HARDENING_PLAN.md` — video/audio quality, cost, publish, ingestion, throughput (21 items).

Nothing here duplicates those. Where a finding touched an already-planned item, only the *net-new* angle
is captured. Most items here are independent and can run in any order; hard-ordered pairs are noted.

## GOAL PROMPT (paste this to Codex to run autonomously to completion)

> **Goal:** implement EVERY item in this document (`docs/RELIABILITY_SECURITY_PLAN.md`), in the listed
> dependency order, one PR each, until the entire Status log at the bottom is checked `[x]` and merged.
> **Do not stop after one item — continue to the next automatically.** Done only when all items are merged green.
>
> **Loop, per item, top-down:**
> 1. Read the item + Standing Constraints. Implement on branch `codex/<slug>`.
> 2. "Done properly" = ALL per-PR verification passes (`ruff format` + `ruff check`, full `pytest` green,
>    `make verify`, `pnpm security:secrets`, empty `git ls-files models secrets.toml`), the item's own tests
>    are real (not stubbed/skipped/`xfail`), CI green, PR merged, branch deleted.
> 3. Tick the item's box in the Status log (commit that update), then start the next item.
> 4. Respect the dependency graph — never start an item before its prerequisites are merged.
>
> **Hard rules (never violate, even to "finish"):**
> - Never publish, schedule, post, or run paid/live generation or ThreadsDashboard/Supabase export. All work
>   is code + tests only. Security items harden the code that runs when a human triggers it — you never trigger it.
> - Never commit secrets or model binaries; never touch `identity_references/`; never loosen the exposure gate
>   or censor legal-adult captions.
> - Never bypass, weaken, `xfail`, or delete a failing test to make CI green. Fix the code. If the whole suite
>   can't pass, STOP.
> - Never fake completion. A box is `[x]` only when truly merged green with real tests.
> - For DB-schema changes: never drop/rename a column that live code reads without migrating existing rows.
>   If a fix needs a backfill you can't safely run headless, ship the forward-compatible code + STOP and ask.
>
> **When to STOP and ask the human:** a product/policy decision (data-retention window, whether to delete a
> standalone CLI, auth model for the local UI), genuine ambiguity where a wrong guess risks correctness or data
> loss, an unsatisfiable prerequisite, or anything the Standing Constraints forbid. Surface specifics, pause,
> resume when answered.

## Standing Constraints (apply to EVERY item)

- **NEVER** publish/schedule/post; **NEVER** run paid/live gen, `--schedule-mode live`, `--enable-live`,
  `--enable-paid-generation`, `export-threadsdash`, or `--allow-unbudgeted-local-test`. Code + tests only.
- **NEVER** commit secrets (`project_data/secrets.toml`) or model binaries (`fetch_models.py` fetches them;
  CI `hygiene` + `secret-scan` block committed binaries).
- Don't touch `identity_references/` (gitignored biometric embeddings). Security items that ADD protection
  around that dir (chmod, path guards, erasure command) are in-scope — but never read/print/commit the vectors.
- Exposure ceiling implied/covered only; don't loosen the exposure gate; don't censor legal-adult captions.
- Keep `python_packages/reel_factory/tests/fixtures/broad_exception_allowlist.txt` line-synced if any
  `except Exception` handler shifts (`test_exception_boundaries.py` checks exact `file:function:line`).
- Leave the unrelated pre-existing Knip edits (`package.json`, `pnpm-lock.yaml`) untouched.
- Higgsfield `kling3_0` has NO seed / NO negative-prompt param — never pass those.
- **Per-PR verification (all must pass before merge):**
  - `uv run --package reel-factory ruff format python_packages/reel_factory/` + `ruff check` same
  - `uv run --directory python_packages/reel_factory python -m pytest -q` (currently **432 passing**; add your tests)
  - For campaign_factory / reference_factory items: run that package's `pytest -q` too
  - For contentforge (Next.js) items: `pnpm --filter contentforge lint` + its test script if present
  - `make verify` · `pnpm security:secrets` · `git ls-files python_packages/reel_factory/models project_data/secrets.toml` → empty
  - Commit trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

## The core problem (why this order)

The learning loop and the output/publish path are being fixed separately. But underneath, the pipeline can
silently lie: a metric re-import crashes on a dateless post, two render workers claim the same job, a nightly
generation run that forgot `--wait` reports "ok" with zero assets on disk, an LLM 429 with a 1-hour timeout
stalls a whole stage, and 60% of the cross-package contracts are validated by nobody so a malformed payload
flows through unchecked. Plus a couple of real security gaps (unauthenticated file-delete routes, biometric
vectors printed to stdout). **Fix the correctness/data-loss bugs first, then external-call robustness, then
security, then operator visibility, then contracts + DB hardening, then debt.**

---

## TIER 0 — Correctness / data-integrity bugs (do first)

### 0.1 `reel_outcomes` re-import crashes on NULL `posted_at`/`account`  ·  HIGH · M · [ ]
**Branch:** `codex/reel-outcomes-upsert-null`
**Why:** conflict target is `ON CONFLICT(filename, platform, account, posted_at)` (`metrics_store.py:283,468`)
but the PK `outcome_id` is deterministic with `'unknown'`/`'account'` fallbacks (`:245`). For a dateless post,
NULLs make the 4-col target not match while the PK *does* collide → `IntegrityError` instead of upsert. Breaks
the normal metric-update path (re-importing a CSV for a post with no date).
**Do:** make `posted_at`/`account` `NOT NULL DEFAULT ''` and coalesce on insert, OR switch the conflict target to
`ON CONFLICT(outcome_id)`. Whichever you pick, existing NULL rows must be handled — coalesce in a one-time
`_ensure_columns`-style backfill.
**Tests:** re-import a dateless/accountless outcome twice → second updates, no `IntegrityError`; dated outcome
upserts as today.
**STOP-and-ask** if a schema backfill on real data would be needed beyond `''`-coalescing.

### 0.2 `render_queue.claim()` can double-claim a job  ·  HIGH · S · [ ]
**Branch:** `codex/render-queue-claim-rowcount`
**Why:** `render_queue.py:79-91` runs a guarded `UPDATE ... WHERE status='queued'` but never checks
`cur.rowcount`; the worker whose UPDATE hit 0 rows still re-SELECTs and returns the row as claimed → two workers
render the same job (wasted work, possible duplicate output).
**Do:** check `cur.rowcount`; if 0, return `None` (job was claimed by another worker).
**Tests:** two concurrent claims of one queued job → exactly one gets it, the other gets `None`.

### 0.3 Contract validation silently no-ops when the package isn't importable  ·  MED-HIGH · S · [ ]
**Branch:** `codex/contract-validation-hard`
**Why:** `still_to_reel.py:391-394` does `try: from pipeline_contracts import validate_motion_edit_render /
except ImportError: return` — in any env where the first-party workspace dep isn't installed, validation becomes
a no-op instead of a hard failure. Validation is best-effort, not guaranteed.
**Do:** let the `ImportError` propagate (it's a first-party workspace dependency; a missing install is a real
error, not a soft-skip). Same pattern anywhere else it appears.
**Tests:** with the dep present, validation runs; the import is not swallowed (assert it raises if forced absent).

---

## TIER 1 — External-call robustness (reliability + protects paid spend)

### 1.1 Harden the reference_factory Higgsfield runner (timeout + status + download verify + job-id persist)  ·  HIGH · M · [ ]
**Branch:** `codex/higgsfield-runner-harden`
**Why:** the `reference_factory/higgsfield_runner.py` `run_daily_generation` path lags the already-hardened
reel_factory adapter (`generate_assets.py:258-321` — copy its patterns). Four bugs:
- **No subprocess timeout:** `_run_command` (`:2505-2506`) is `subprocess.run(..., check=False)` with no `timeout=`;
  under `--wait` (RUNBOOK-recommended, `cli.py:558/612`) the CLI blocks on internal polling → a stuck job hangs the
  whole nightly process forever. Add `timeout=N`, raise on `TimeoutExpired`.
- **Silent no-op batch:** default `wait=False` (`:62,226`); with no downloaded asset, `_materialize_result_asset`
  returns `None` but line 1000 sets `status="generated"` unconditionally → `_manifest_status` reports "ok". Forget
  `--wait` and every run silently produces nothing while claiming success + orphaning paid jobs. Fix: if not `wait`
  and no asset, status `submitted`/`pending`, not `generated`.
- **Provider status never checked on primary image/video:** `_run_json` (`:2488-2498`) checks only returncode +
  JSON-parse; `BLOCKED_PROVIDER_STATUSES`/`FAILED_PROVIDER_STATUSES` (`:33-41`) are consulted only for variation
  grids (`_variation_status`, `:1639-1651`). A `status:"moderated"/"failed"` response with no URL becomes a
  "generated" asset. Fix: run the status check on primary results too; fail the run on blocked/failed.
- **Downloads unverified + no timeout:** `:2534` `urllib.request.urlretrieve` (also `generate_assets.py:663`
  `download_result`) — no socket timeout, no size/non-empty check; a truncated/0-byte file is copied forward as
  good. Fix: `urlopen(timeout=)`, assert `st_size > threshold` before accepting.
- **Re-pay window:** job ID persisted only after the full result returns (`:790-795,990-994`); a crash during a
  paid submit loses the ID → re-run re-pays. Fix: persist the submitted job ID to disk immediately on submit.
**Tests:** timeout raises (mock a hanging child); `wait=False` + no asset → `submitted` not `generated`; moderated
status → run fails; truncated download rejected; job-id file written at submit. Use the injectable/mockable seams;
NO real paid calls.

### 1.2 Shared LLM-call resilience helper (timeout + retry + defensive parse)  ·  HIGH · M · [ ]
**Branch:** `codex/llm-call-resilience`
**Why:** every external LLM call is one-shot with a pathological timeout:
- `call_grok` default `timeout=3600` (1 hour) (`generate_prompts.py:1521`), used by `reference_analyzer.py:296`,
  `anatomy_qc.py:73`, `generate_prompts.py:1823` — a hung socket stalls the stage for an hour.
- Zero retry/backoff on 429/5xx/timeout: `call_grok` (`:1520-1534`), `call_gemini_motion` (`:1440`),
  `_grok_reference_image` (`reference_intake.py:3476`). The `:1813-1859` loop is a validator re-prompt, not a
  transport retry — `call_grok` at `:1823` sits outside its `try`, so a 429 propagates out. Compounds the
  fail-closed QC: one transient 429 discards an already-paid image (the memory-noted false-reject symptom).
- `reference_analyzer.py:298` bare `json.loads(text)` — malformed/truncated Grok JSON crashes `analyze_reference`
  (siblings `anatomy_qc.py:106-116` + `generate_prompts.parse_prompt_text:1504-1517` already guard this).
- Gemini `client.models.generate_content` (`reference_intake.py:682`) — no explicit per-call timeout.
**Do:** one shared helper (3 tries, exp backoff on HTTPError 429/5xx + URLError/timeout, explicit ~60-120s timeout,
defensive JSON decode with the existing heuristic fallback). Route all the above through it. Copy the good pattern
already at `reference_intake._grok_reference_image` (`:3475-3494`: explicit `timeout=120`, billing-error handling,
`response_format: json_object`, presence checks).
**Tests:** a 429-then-200 mock transport → succeeds after retry; malformed JSON → fallback, no crash; timeout is
bounded (assert the value passed to the transport). No live API calls.

---

## TIER 2 — Security / privacy (net-new; core injection premise is already well-defended)

> Context: the audit confirmed the system is architecturally sound on injection — references enter models
> VISUALLY not as prompt text; no SQL injection (all `?`-bound), no command injection (no `shell=True`, list-arg
> subprocess, captions rasterized to PNG so no ffmpeg `drawtext` injection), no secret leakage (keys only in
> Authorization headers, stripped from lineage). These items close the remaining real gaps.

### 2.1 Authenticate the ContentForge Next.js API (unauthenticated file-delete routes)  ·  HIGH · M · [ ]
**Branch:** `codex/contentforge-api-auth`
**Why:** `apps/contentforge` has no `middleware.ts` and no session/token check anywhere — every route is open to
any local process, and to any website the operator visits (CSRF simple-POST / DNS-rebinding). Reachable
destructive routes: `app/api/runs/route.js:24` (DELETE `deleteRun`) + `:13` (bulk `cleanupOldFiles`),
`app/api/runs/cleanup/route.js:6`, `app/api/detector/route.js:17` (DELETE `deleteRunFiles`),
`app/api/storage/cleanup/route.js:22` (only guard is a `confirm:true` body flag the attacker supplies).
**Do:** add a `middleware.ts` requiring a local token header (mirror reel_factory's `CREATOR_OS_API_TOKEN`), or at
minimum validate `Origin`/`Host` against localhost to defeat DNS-rebinding. Document the token in `.env.example`.
**Tests:** a request without the token/allowed-origin is rejected; a valid local request passes. (Next.js route or
middleware unit test.)

### 2.2 Stop leaking biometric face embeddings + add an erasure path  ·  HIGH(privacy) · M · [ ]
**Branch:** `codex/identity-privacy`
**Why:** GDPR special-category biometric data is mishandled:
- `identity_verification.py:437` `print(json.dumps(result...))` where `result` includes raw ArcFace `embeddings` →
  any CLI log / CI capture leaks vectors.
- `:270-283` writes vectors as plaintext JSON, world-readable (umask 644), no encryption, no TTL, and there's no
  delete subcommand → right-to-erasure gap.
- `--output` (`:211-215,397`) isn't constrained to the gitignored `identity_references/`, so vectors can be written
  into a committed dir.
- `reference_factory/embeddings.py:175-179` DINOv2 `embedding_cache/*.json` is neither committed nor gitignored →
  latent `git add` exposure.
**Do:** (a) emit counts + `referenceSetId` only by default, gate raw vectors behind explicit `--json-embeddings`;
(b) add `identity-reference-delete --creator`; (c) `os.chmod(0o600)` the file, `0o700` the dir; (d) validate
`--output` resolves under `identity_references/`; (e) add `embedding_cache/` to `.gitignore`.
**Tests:** default CLI output contains no `embeddings` array; delete removes the set; chmod asserted; out-of-dir
`--output` rejected. Do NOT commit or print any real vector in a test fixture.

### 2.3 Fence + scrub `analysis_context` before it enters the prompt LLM (second-order injection)  ·  MED · S · [ ]
**Branch:** `codex/scrub-analysis-context`
**Why:** vision-analysis JSON is raw `json.dumps`'d into the prompt-builder LLM instruction at
`generate_prompts.py:1699-1701`; the existing `_safe_fragment` scrubber is applied only in
`compile_prompt_contract` (`:1266-1300`), not here. Adversarial text rendered inside a competitor frame can be
transcribed into `analysis_context` and laundered into generation. (Severity capped by the downstream human
approval gate — worst case is skewed prompts / wasted paid gen, not auto-publish or exfil.)
**Do:** apply `_safe_fragment` (or equivalent fence) to `analysis_context` before it joins `merged_direction`.
**Tests:** an `analysis_context` containing an injected instruction string is neutralized/fenced in the built prompt.

### 2.4 Security hardening batch (SSRF + gitignore + gitleaks + path guard)  ·  MED-LOW · S · [ ]
**Branch:** `codex/security-hardening-batch`
**Why (small, independent, batch into one PR):**
- **SSRF:** `reel_url_import._validate_url` (`:14-19`) allows any http/https host — `http://169.254.169.254/…`
  reachable via yt-dlp. Reject private/loopback/link-local resolved IPs before invoking yt-dlp.
- **gitleaks default rules off:** `.gitleaks.toml` defines only `juno-api-key`, no `[extend] useDefault=true` → a
  standalone `gitleaks detect` misses an `xai-…` key in a tracked file. Add `[extend] useDefault=true`.
- **Root `.gitignore` lacks a global secrets rule:** protection relies on the nested reel_factory ignore. Add
  `secrets.toml` / `*.secrets.toml` to root `.gitignore`.
- **Path-traversal defense-in-depth:** `download_reel_url` (`reel_url_import.py:59/62`) trusts `stem`; safe today
  only because the sole caller gates via `_safe_stem`. Reject path separators inside `download_reel_url` itself.
**Tests:** a link-local URL is rejected; `gitleaks`/ignore config changes verified by a config-content test or
`make verify`; a `stem` with a separator is rejected.

---

## TIER 3 — Operator-UI reliability (human-in-the-loop must be trustworthy)

### 3.1 Run paid generation as background jobs, not inside the HTTP request  ·  HIGH · L · [ ]
**Branch:** `codex/reelgui-async-gen`
**Why:** `reel_gui.py:2033-2038` (`create_video_asset(..., wait=True)`), `:2077` (render-pack), and the grid
fan-out `:2119-2175` (N serial paid video gens — a 6-panel grid = 6×10-30min) all run synchronously inside one
blocking POST. No job id, no progress, no cancel; a browser/proxy timeout loses the state. `/api/run` already does
this correctly (threaded + `/api/run/status` polling, `:2861-2970`) — mirror it.
**Do:** return a job id immediately, run gen in a background thread, expose a per-job status endpoint; the grid
fan-out enqueues per-panel jobs and streams per-panel status.
**Tests:** POST returns a job id without blocking; status endpoint reports running→done; a second concurrent gen is
handled (queued or rejected, not corrupt).

### 3.2 Stop double-billing: in-flight disable + idempotency on paid buttons  ·  HIGH · S · [ ]
**Branch:** `codex/reelgui-gen-idempotency`
**Why:** `static/app.js:2013` (`createKlingVideo`), `:1884` (fanout), `:2077` (render-pack) only gate the first
click with `confirm()`; nothing disables the button or debounces while in-flight, and the endpoints aren't
idempotent → a double-click bills a second Kling job.
**Do:** disable the button + set an in-flight flag until the promise settles (client); add a client-supplied
idempotency key the server dedupes on (pairs with 3.1's job model).
**Tests:** rapid double-invoke fires one job; the button is disabled while in-flight.

### 3.3 Surface silent failures across both UIs  ·  HIGH · M · [ ]
**Branch:** `codex/ui-surface-failures`
**Why:** failures are invisible in several spots:
- reel_gui: run-progress parser counts QC-`skip` (reject) lines as `completed` (`reel_gui.py:598-600`); only `FAIL`
  bumps `failed` → AI-QC rejects inflate "completed" with no reject count/reason. Frontend renders zero
  anatomy/exposure/identity verdicts. ~57/64 `fetch()` calls have no try/catch and there's no global
  `unhandledrejection` handler (`static/app.js`) → a non-JSON 500 leaves status stuck on "running" forever.
- ContentForge: failed `/api/scan-output` renders as a clean populated grid (`ResultsGrid.jsx:167-180` empty catch,
  no `res.ok`; count falls back to `forgeResult.total` at `:235`); cross-variant similarity table silently vanishes
  on detector failure (`:182-197,311-348`); rejected-candidate reasons are computed (`lib/pipeline.js:376-401`) then
  dropped from the manifest (`lib/reels.js:488-489`) and never rendered (`ResultsGrid.jsx:250-255` bare count).
**Do:** (a) parse `skip`/reject into a distinct `rejected` counter with reason tallies in `/api/run/status`;
(b) wrap gen fetches in try/catch that reset status + flash, add a global `unhandledrejection` toast; (c) in
ContentForge, add error state + banner on scan failure (don't fall back to `forgeResult.total`), track detector
error separately ("similarity unavailable"), keep `rejectionSamples` in the analyze result and render a
reason→count breakdown.
**Tests:** a QC-reject shows as rejected-with-reason not completed; a mocked 500 flips the UI to an error state
(component/route tests); rejection reasons reach the manifest.

### 3.4 Fix the onboarding cliff + subprocess timeouts + health view  ·  MED · M · [ ]
**Branch:** `codex/reelgui-onboarding-health`
**Why:**
- Fresh launch 401s: loopback needs `ALLOW_INSECURE_LOCAL` truthy AND no token (`local_api_auth.py:44-53`); the
  launcher/`setup.sh` never export it and it's in no README → the only working mode is tribal knowledge. (If a token
  IS set, the served frontend sends no `Authorization` header, so the GUI breaks.)
- Sync subprocess calls with no `timeout=`: render-pack `:2382`, clip preview `:2741`, ffprobe `:1627/:1666` — a
  hung child wedges the request + a threadpool slot forever.
- Partial health view: `/api/dashboard/summary` (`:1060-1072`) omits in-flight gens, failed gens, spend, and queue
  depth — no single place the operator sees live pipeline health.
**Do:** (a) export `ALLOW_INSECURE_LOCAL=1` in the launcher OR default-allow loopback when no token is configured,
and document it (coordinate with 2.1's token model — pick ONE auth story and write it down); (b) add `timeout=` +
a clear 504-style error to those subprocess calls; (c) fold in-flight jobs + failed count + cost + queue depth into
the dashboard summary.
**Tests:** fresh launch (no env) serves `/` without 401 under the chosen model; a hung subprocess returns an error
not a hang (mock); summary includes the new fields.
**STOP-and-ask:** confirm the auth model (token vs default-allow-loopback) with the human before finalizing — it's
a security/UX tradeoff that must agree with item 2.1.

### 3.5 ContentForge review polish (dead gates, fake stats, rationale, skeletons)  ·  LOW-MED · M · [ ]
**Branch:** `codex/contentforge-review-polish`
**Why (batch):** model-backed creative-quality/virality gates (`lib/video-analysis-gate.js`,
`lib/virality-gate.js`) only fire when the caller passes reports, but the sole caller posts only `layers`
(`SimilarityChecker.jsx:501-503`) → dead path (wire in or delete). Hardcoded "Warnings 0%" +
"Selected outputs = count" tiles (`ResultsGrid.jsx:396-407`) read as a real all-clear. No compare / no "why ranked
#1" rationale, score table unsorted (`VariationLabPanel.jsx:148-184`). Missing loading skeletons
(`ReelsReadinessPanel.jsx:58-61`, ResultsGrid). RunHistory delete is fire-and-forget, no `res.ok` (`:35,45`).
**Do:** wire or delete the dead gates (ask which); compute the stat tiles from real QA signals or remove them; sort
by score + badge #1 + one-line driver rationale; add skeletons while `loading && !data`; check `res.ok` on
RunHistory ops.
**STOP-and-ask:** whether to wire vs delete the video-analysis/virality gates (they cost Higgsfield credits).

---

## TIER 4 — Enforce the cross-package contracts (silent-corruption guard)

### 4.1 Enforce contracts at producer write boundaries  ·  HIGH · M · [ ]
**Branch:** `codex/enforce-contracts`
**Why:** the contract layer is ~60% decorative. 11 of 18 contracts are emitted across package boundaries but
validated by NObody (no production call sites, only tests/re-exports): `audio_intent`,
`caption_outcome_context`, `pattern_card`, `video_analysis`, `higgsfield_soul_image_prompt`,
`kling_3_video_prompt`, `generated_asset_lineage`, `creative_plan`, `recommendation_next_batch`,
`recommendation_accuracy_report`, `repurposing_plan` (`validator.py:105-203` defines all; 0 call sites outside
`contracts.py`/tests). `reference_factory` imports `pipeline_contracts` zero times despite owning 5 schemas.
`generated_asset_lineage` is stamped in ~15 modules (`still_to_reel.py:317`) and the pipeline BLOCKS on a missing
lineage (`review_batch_guard.py:303`) yet never validates its shape — a malformed lineage passes review. Its `$id`
also wrongly says `campaign_factory.*` while reel_factory is the producer.
**Do:** call the matching validator at each producer's write boundary (18 sites, mechanical) — at minimum the
high-traffic ones: `generated_asset_lineage` in `still_to_reel._build_lineage`, the reference_factory 4
(`video_analysis`, `pattern_card`, `higgsfield_soul_image_prompt`, `kling_3_video_prompt`) on emit,
`caption_outcome_context`, `creative_plan`, `recommendation_next_batch`. Correct the `generated_asset_lineage`
`$id` owner. Validation failures should raise (fail-closed), not warn.
**Tests:** a malformed payload for each newly-enforced contract raises at the write boundary; valid payloads pass.
Coordinate the `recommendation_next_batch` change with the sibling doc's "unify next_batch schema" item (this is
the *enforcement* half; that was the *shape* half).

### 4.2 De-duplicate the committed schema copies + validator footgun  ·  MED · S · [ ]
**Branch:** `codex/dedupe-schema-copies`
**Why:** all 18 schemas exist twice, both git-tracked — `packages/pipeline_contracts/schemas/*.json` (source) and
`packages/pipeline_contracts/pipeline_contracts/schemas/*.json` (packaged); `validator.py:13-15` prefers the inner
copy, and `campaign_factory/control.py:87` reads a third path (`settings.root/schemas`). Byte-identical today but
nothing enforces it → editing the obvious source leaves the validator on the stale inner copy. Also
`validator.py:226` reassigns the `value` function parameter inside the loop (harmless now, latent footgun).
**Do:** make the packaged copy a build artifact or add a CI test asserting the two dirs are byte-equal; rename the
shadowed `value` param to `field_value`.
**Tests:** a CI/unit test fails if the two schema dirs diverge.

---

## TIER 5 — DB hardening (concurrency + migrations + perf)

### 5.1 Shared-DB connections: 30s timeout + WAL everywhere  ·  MED-HIGH · S · [ ]
**Branch:** `codex/db-connect-timeout-wal`
**Why:** `metrics_store` opens the shared DB with bare `sqlite3.connect(db_path)` (default 5s busy-timeout) at
`:58,162,366,559,579,650,762` while running the heaviest write loops; every other opener passes `timeout=30.0` +
WAL (`manifest.py:44,55`). Against a render worker holding the lock >5s → `database is locked`, failed import. And
whichever process opens a fresh DB first decides journal mode, so an early metrics import can leave it in
rollback-journal mode.
**Do:** add `timeout=30` + `PRAGMA journal_mode=WAL; PRAGMA busy_timeout` on every `metrics_store` connect (share
one helper with the other openers).
**Tests:** connections use the helper (assert timeout/pragmas); a contended write retries rather than failing fast
(can simulate with a held lock).

### 5.2 Real schema migrations (columns added to shipped tables break old DBs)  ·  MED · M-L · [ ]
**Branch:** `codex/schema-migrations`
**Why:** `PRAGMA user_version` is written once (`manifest.py:173`) but never read; `schema_migrations` gets one
`INSERT OR IGNORE` and is never consulted. Everything is `CREATE TABLE IF NOT EXISTS` + hand-maintained
`_ensure_columns` allowlists, and `reference_factory/db.py:348` migrates only 2 of ~12 tables → a new column on a
shipped table (`audio_catalog.danceability`, etc.) raises `no such column` on a pre-existing DB.
**Do:** add a generic idempotent "diff the declared schema vs `PRAGMA table_info` for every table, `ADD COLUMN` the
missing ones" pass run at store-open (or real `user_version` migrations). Cover all tables, not a hand-picked few.
**Tests:** open an old DB missing a recently-added column → the pass adds it, no `no such column`; a current DB is
unchanged.
**STOP-and-ask** before any column DROP/RENAME on data you can't safely migrate headless.

### 5.3 Add the missing hot-path indexes  ·  MED · S-M · [ ]
**Branch:** `codex/db-hot-indexes`
**Why:** unindexed hot lookups: leading-wildcard `WHERE output_path LIKE '%/'||filename` run per-row during import
(`manifest.py:446`, `metrics_store.py:859,864`); `posting_slots` filtered by `rendered_output_path` (no index) and
by `content_fingerprint` alone (can't use the `(account_id, content_fingerprint)` composite) —
`posting_ledger.py:854`, `metrics_store.py:893`; `cost_tracker.ensure_cost_table()` runs full DDL + `executescript`
(forces COMMIT) on *every* insert (`cost_tracker.py:122`).
**Do:** store + join an indexed `filename` column instead of the LIKE (overlaps the sibling doc's "stable join
keys" — coordinate; here it's the index, there it's the key semantics); add indexes on
`posting_slots(rendered_output_path)` and a usable `content_fingerprint` index; move `ensure_cost_table` to
connection setup, not per-insert.
**Tests:** the join uses the index (EXPLAIN QUERY PLAN assertion or a timing smoke test); cost insert no longer
re-runs DDL.

### 5.4 `intelligence_store` cross-table column migration ordering  ·  LOW · S · [ ]
**Branch:** `codex/intelligence-store-ordering`
**Why:** `intelligence_store.py:214` `_ensure_columns("operator_ratings", …)` on a table created by
`campaign_store.py`; it early-returns if absent (`:265`) then `:465` `SELECT ... FROM operator_ratings` raises if
run standalone. Latent but fragile.
**Do:** guard the `SELECT` behind the same existence check, or ensure the table is created before either store
touches it.
**Tests:** `intelligence_store` run against a DB without `operator_ratings` degrades gracefully, no raise.

---

## TIER 6 — Dead code / debt cleanup (do last; low risk, high clarity)

### 6.1 Delete dead modules + dead functions  ·  LOW · S · [ ]
**Branch:** `codex/delete-dead-code`
**Why:** zero-importer modules: `reel_factory/probe.py` (7-line re-export shim), `campaign_factory/readiness.py:9`
(orphan dup of live `execution_readiness.py:258`), `reel_factory/reel_motion_prompt.py`,
`reel_factory/experiments/tribev2_score_generated_panels.py`. Zero-ref functions: `import_audit_manifest`
(`adapters/contentforge.py:823`), `format_cost_report` (`cost_tracker.py:253`), `latest_rating_for_output`
(`campaign_store.py:790`).
**Do:** delete them. **DO NOT** delete `deprecated_generators.py` — it's live (`reel_gui.py:65`,
`generate_assets.py:24`) despite the name; rename it if anything, in a separate PR.
**STOP-and-ask** before touching the standalone CLIs (`review_truth.py`, `reference_grid_production.py`,
`approval_board.py`, `overnight_grid_worker.py`, `review_batch_guard.py`) — some may be intentionally
operator-invoked; confirm per file.
**Tests:** suite still green after removal (proves zero importers).

### 6.2 Consolidate drifted `_load_json`/`_read_json`/`slugify` + fix config drift  ·  LOW · M · [ ]
**Branch:** `codex/consolidate-helpers-config`
**Why:** `_load_json` has three incompatible contracts under one name — returns `None` (`metrics_store.py:942`,
`caption_bank.py:813`), returns `[]` and raises on bad JSON (`audio_provider.py:73`), or raises ValueError
(`creator_os_cli.py:15`); same for `_read_json`. `slugify` empty-input fallback drifts: `campaign_{timestamp}`
(`campaign_store.py:127`) vs `"untitled"` (`core.py:217`). Config drift: `SSCD_MODEL_PATH` (code,
`sscd_video.py:27`) vs documented `CONTENTFORGE_SSCD_MODEL_PATH` (`.env.example:54`) — documented var has no
effect; paid-budget vars `HIGGSFIELD_DAILY_BUDGET_USD`/`RUN_MAX_ASSETS`/`MIN_BALANCE_USD`
(`higgsfield_cost_preflight.py:119-125`) undocumented; `CONTENTFORGE_URL` (`.env.example:29`) dead (code reads
`CONTENTFORGE_BASE_URL`); undocumented kill-switch `CREATOR_OS_PROACTIVE_CYCLE_DISABLED`.
**Do:** one shared json-load helper with an explicit contract (pick `None`-on-missing, raise-on-malformed);
one `slugify`; align env-var names + document the budget vars and kill-switch in `.env.example`; drop the dead one.
**Tests:** the shared helper's contract is tested once; a smoke test that documented env vars match the names code reads.

### 6.3 Fix `virality_select` reward basis (leftover raw-view weighting)  ·  MED · S · [ ]
**Branch:** `codex/virality-select-reward`
**Why:** `virality_select.py:25` `avg_winner_score` still uses the legacy raw-view-weighted reward, contradicting
the module's own docstring — the restored predict-and-select ranker ranks candidates on the wrong reward basis.
Net-new vs the "restore virality_select" item (that was recovery; this is the reward correctness).
**Do:** switch it to the shared engagement-rate helper from the sibling doc's item 1.2 (if merged) or inline the
rate formula. Depends on that helper existing; if not yet merged, STOP and note the dependency.
**Tests:** a high-rate/low-view candidate outranks a low-rate/viral one.
**Depends on:** learning-doc item 1.2 (engagement-rate reward helper).

---

## Dependency / sequence summary

```
0.1, 0.2, 0.3  correctness bugs — do first, independent
1.1 higgsfield-runner-harden ─ independent   1.2 llm-resilience ─ independent
2.1 contentforge-auth ↔ 3.4 onboarding-auth  (MUST agree on one auth model)
2.2/2.3/2.4 security — independent
3.1 async-gen ─► 3.2 idempotency (shares the job model)
3.3, 3.5 — independent    3.4 depends on the 2.1 auth decision
4.1 enforce-contracts (coordinate recommendation_next_batch w/ sibling "unify schema")
4.2 dedupe-schemas — independent
5.1 db-timeout ─ independent   5.2 migrations ─ independent
5.3 hot-indexes (coordinate w/ sibling "stable join keys")   5.4 — independent
6.1 dead-code, 6.2 helpers/config — do last
6.3 virality reward — depends on learning-doc 1.2
```

**Recommended first cut:** 0.1 → 0.2 → 0.3 (correctness) → 1.1 → 1.2 (don't burn paid gen on hangs) →
2.1 + 2.2 (real security gaps) → 3.1/3.2/3.3 (operator can't fly blind) → 4.1 → 5.1 → then the rest.
Only 6.3→(learning 1.2), 2.1↔3.4, and 3.1→3.2 are hard-ordered.

## Status log
- [x] 0.1 reel_outcomes NULL upsert crash — PR #335
- [x] 0.2 render_queue double-claim — PR #336
- [ ] 0.3 contract validation silent no-op
- [ ] 1.1 harden higgsfield runner (timeout/status/download/job-id)
- [ ] 1.2 shared LLM resilience helper
- [ ] 2.1 contentforge API auth
- [ ] 2.2 biometric privacy (stdout/erasure/chmod/gitignore)
- [ ] 2.3 scrub analysis_context
- [ ] 2.4 security hardening batch (SSRF/gitleaks/gitignore/path)
- [ ] 3.1 async paid-gen jobs
- [ ] 3.2 gen idempotency / no double-bill
- [ ] 3.3 surface silent failures (both UIs)
- [ ] 3.4 onboarding + subprocess timeouts + health view
- [ ] 3.5 contentforge review polish
- [ ] 4.1 enforce contracts at write boundaries
- [ ] 4.2 dedupe schema copies + validator footgun
- [ ] 5.1 db connect timeout + WAL
- [ ] 5.2 schema migrations
- [ ] 5.3 hot-path indexes
- [ ] 5.4 intelligence_store ordering
- [ ] 6.1 delete dead code
- [ ] 6.2 consolidate helpers + config drift
- [ ] 6.3 virality_select reward basis

## Verified-solid (audited, do NOT "fix")
- **No SQL injection** anywhere — all values `?`-bound; interpolated identifiers are hardcoded/whitelisted.
- **No command injection** — no `shell=True`/`os.system`; list-arg subprocess; captions rasterized to PNG (no ffmpeg `drawtext` vector).
- **No secret leakage** — keys only in `Authorization`/`apikey` headers, stripped from lineage (`outcomes.py:127`); nothing sensitive tracked.
- **reel_factory auth default-closed**; path traversal blocked by `_safe_in_root`/`_safe_stem`; ContentForge file access funnels through `lib/paths.js`.
- **Supabase service-role is CLI-only** (not web-reachable); CORS clean; no biometric data committed/returned by any API.
- **Transactions atomic** (single trailing commit, rollback on close); UNIQUE coverage good except item 0.1.
- **The core handoff contracts ARE enforced** (`campaign_draft_payload`/`threadsdash_draft`/`variant_assignment`/`motion_edit_render`/`front_generation_plan`); no version drift — all `.v1`, consumers match.
- reel_factory's `HiggsfieldCliAdapter` is the hardened reference implementation (30-min timeout, status classification, defensive JSON) — item 1.1 brings the reference_factory runner up to it.

## Dropped after verification (false positives — do NOT chase)
- Kling seed / negative-prompt — not exposed by `kling3_0`.
- `reel_motion_prompt.py` as a *quality* gap — it's dead code (delete in 6.1, don't wire).
- Global LLM throttle — no API fan-out exists (QC/prompt-gen are sequential loops); the false-reject symptom is a retry gap (1.2), not parallelism.

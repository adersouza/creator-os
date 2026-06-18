# Track AP→9 — Codex prompt (autoposter 8.7 → ≥9)

**Context for the owner (not part of the prompt):** AP0–AP3 are SHIPPED to ThreadsDashboard `main` (`ec2190b5e`). The autoposter is already ~8.7/10. The remaining lift to a confident 9 is **verification depth + ops wiring + merge cleanup — not new features**. The three gaps below were verified directly against `origin/main` (the infra to close each already exists; this is connect-and-prove work, not build-from-scratch).

---

## Prompt to give Codex

> **Repo:** ThreadsDashboard (the autoposter source of truth). Work on a feature branch off `main` (`ec2190b5e` or later), open a PR, do **not** push to `main` directly. One logical change per PR; each PR adds the test that proves it; targeted `vitest` + `compat:check` + `typecheck` + `build` green before commit.
>
> **Goal:** take the autoposter from ~8.7 to ≥9/10. AP0–AP3 are already shipped — do **not** re-implement them. This is verification + observability + cleanup. Five PRs, in this order:
>
> ### PR 1 — IG publish failure-branch e2e (highest value)
> `e2e/publish-threads.spec.ts` already exercises failure modes; `e2e/publish-instagram.spec.ts` (196 lines) and `e2e/post-lifecycle.spec.ts` (271 lines) are **happy-path only**. Bring IG to parity with Threads. Add e2e cases that drive the real error taxonomy (from `api/_lib/metaErrors.ts`) through the **publish-path reaction**, not just the classifier:
> - **transient** (codes 1/2/17/341/368/500/503, subcodes 2207001/2207027/2207053/2207082) → post stays `scheduled`, retried, not failed.
> - **window_cap** → backed off until `estimated_time_to_regain_access`, then resumes.
> - **permanent** (caption_too_long / media_inaccessible / non-retryable set) → `failed` immediately, no retry storm.
> - **media-not-ready** (9007 / 2207027) → container re-poll, eventual publish, **no duplicate**.
> - In `post-lifecycle.spec.ts`, add the failure→retry→success and failure→dead-letter state transitions.
> Use the existing fake/mocked Meta Graph harness from `publish-threads.spec.ts`; mirror its structure. `metaErrors.test.ts` already covers classification — this PR covers the **publish path's response** to each class for Instagram.
>
> ### PR 2 — double-publish concurrency proof
> `tests/unit/accountSync.test.ts` already proves concurrent-sync safety ("two concurrent syncs for same account: second is skipped"). **No equivalent exists for the publish claim.** Add a test that spawns N parallel workers attempting to publish the **same** scheduled post and asserts the atomic `scheduled → publishing` claim (`publishing_started_at`) lets **exactly one** through — the rest see the row already claimed and skip. Cover both `processScheduledPosts` (cron path) and `publishSinglePost` (`publishPost.ts` atomic re-check). The race fixes are correct by construction; this PR **proves** it under contention. Reuse the concurrency-test pattern already in `accountSync.test.ts`.
>
> ### PR 3 — wire AP2/AP3 signals into the existing alerter
> `api/_lib/alerting.ts` is a real Discord webhook (`DISCORD_ALERT_WEBHOOK_URL`), already called by shadowban-scanner, account-retirement, token-health, cost-digest, weekly-reports. It is **not** called by the autoposter hardening signals. Wire these three, with sensible thresholds + de-dup (don't spam — one alert per incident, not per cron tick):
> - **AP3 account-health auto-backoff** (`accountHealthAutoBackoff.ts` / `account-health-scorer.ts`): fire an alert when an account transitions to `pause` (suppressed/shadowban_throttle) and again on `resume`.
> - **Publish dead-letter growth**: alert when the publish DLQ (failed/dead-lettered posts, not the webhook-event DLQ that `dlq-sweep.ts` handles) crosses a threshold in a window.
> - **AP2 run-report anomaly**: alert when a publish-worker run report shows phase starvation, abnormal failure rate, or quota exhaustion.
> Add `alerting.test.ts`-style coverage asserting each path calls the alerter once per incident. Goal: ops gets **paged on degradation**, not discovers it later.
>
> ### PR 4 — merge-debt cleanup
> AP0–AP3 wove ~16 branches (6 colliding on `publishInstagram.ts`). Sweep the merged publish path (`publishInstagram.ts`, `publishPost.ts`, `scheduled-posts/*`) for: duplicated retry/backoff logic, dead code paths from the merge, and inconsistent use of the `transitionPostStatus` chokepoint (confirm **every** status write goes through it — no stragglers). Clear the 13 lint warnings flagged at integration. No behavior change; this is the maintainability sub-score (8→9).
>
> ### PR 5 — token-at-rest rotation story
> AP1-3 shipped **ingest-secret** rotation. Document (and, if missing, implement) the encrypted IG/Threads **access-token** refresh + rotation cadence: where tokens are encrypted at rest, when they refresh (401 path exists via `refreshThreadsToken`), and the rotation/expiry policy. A short `docs/` page + any gap-closing code. Closes the security sub-score.
>
> **Non-negotiable constraints (carry from the autoposter hardening work):**
> - This is the autoposter's safety/reliability tier — **no posting-behavior or evasion changes.** No antidetect/proxy/CIB tactics; account-health is detect-and-respect (pause a suppressed account, don't hide it).
> - Don't lower any quality/safety gate. Verification only strengthens.
> - One logical change per PR; tests prove each fix; full gate green before commit.
> - Don't re-implement shipped AP0–AP3 — verify and observe them.

---

## Verified findings backing each PR (for the owner)

| PR | What was checked on `origin/main` | Result |
|----|-----------------------------------|--------|
| 1 | `e2e/publish-{instagram,threads}.spec.ts`, `post-lifecycle.spec.ts` failure-keyword count | Threads 13 / **IG 0 / lifecycle 0** → IG + lifecycle happy-path only |
| 1 | `tests/unit/metaErrors.test.ts` | Classifier well-tested (15 taxonomy hits / 112 lines) — but classification ≠ publish-path reaction |
| 2 | concurrency/double-publish test on the publish claim | Exists for **sync** (`accountSync.test.ts`), **absent for publish** |
| 3 | callers of `alerting.ts` (`sendAlert`/Discord webhook) | 6 callers — **none are AP2/AP3** (account-health pause, publish DLQ, run-reports) |

**Net:** all three are real gaps, each closable with infra already in the repo. Estimated ~5 focused, low-risk PRs to a confident 9.

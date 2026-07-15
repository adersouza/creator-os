# Creator OS Stabilize/Simplify Readiness

Date: 2026-07-15

This report keeps source, CI, runtime, live seams, providers, publishing, and
measured learning separate. A local implementation or passing test is not a
production proof.

## Source Implementation

The stabilization branch implements the following reversible source changes:

- canonical private state, artifact, model, and log roots under
  `~/.creator-os`, with explicit component overrides for rollback;
- copy-only SQLite `VACUUM INTO` migration, integrity/count/hash/permission
  proof, backup verification, and seven-day plus one-operating-cycle retention;
- source/runtime SHA and cleanliness reporting through `creator-os status`;
- a zero-product-write, HMAC-authenticated ThreadsDashboard handshake contract
  and endpoint implementation;
- provider capability/model/workspace/balance/free-quote probes that cannot
  create media or cost events;
- Campaign `performance_snapshots` as the only measured-facts ledger and a
  versioned `reference_factory.knowledge_pack.v1` import/export boundary;
- one Campaign generation coordinator with five explicit modes;
- Campaign-owned provider quotes, policy, signed one-time authorizations, and
  authoritative cost events; Reel can only validate an exact execution scope;
- removal of legacy direct post/schedule writes, preview scheduling, Campaign
  proactive aliases, Reel posting/approval/experiment/outcome/cost ownership,
  and Reference paid-generation ownership;
- every active Campaign module below 1,500 lines, with the former forwarding
  facade and double-delegation chain removed;
- Promptfoo offline regressions, PySceneDetect reference-video preflight, and
  hypothesis-jsonschema contract fuzzing.

Creator OS still has no scheduling or publishing command. ThreadsDashboard is
the sole approval, scheduling, publishing, and Instagram account authority.

## Evidence Ledger

| Surface | Current status | Evidence required for PASS |
|---|---|---|
| Source | PASS locally | clean tree; `make verify` passed: ContentForge 129, contracts 24 TS + 54 Python, Core 16, Campaign 687, Reference 111, Reel 435, integration 63, offline prompt regressions 3/3; architecture, artifacts, and secret scan passed |
| CI | NOT_RUN | required GitHub checks on the pushed branch/PR |
| Runtime | FAIL on the pre-cutover status check | runtime is still at `2d605a3b`, does not match the reviewed source, and contains untracked runtime artifacts; require a clean exact-SHA runtime and verified LaunchAgent paths |
| Canonical state | NOT_RUN | applied migration manifest, verified restore, switched private env, and one complete operating cycle |
| ThreadsDashboard seam | NOT_RUN live | source endpoint is merged in ThreadsDashboard, but the local handshake URL/secret are not configured; require a deployed valid request with zero product writes plus invalid/stale/replay rejection |
| Providers | FAIL closed before network generation | live-read-only probe stopped because the canonical artifact workspace is not ready; require capability/model/workspace/balance/free-quote PASS with zero media and zero cost events; paid smoke remains separately approved |
| Publishing | Unchanged and out of scope for this source repair | existing ThreadsDashboard production evidence; Creator OS must remain unable to publish |
| Measured learning | NOT_PROVEN | exact Instagram/account/asset lineage plus real 1h/24h/72h snapshots and idempotent knowledge fanout |
| Operational cohort | NOT_PROVEN | 10 consecutive correctly reconciled posts |
| Autonomous learning promotion | BLOCKED by evidence gate | 50 eligible posts with both real 1h and 24h measurements |

The current runtime checkout predates this repair and contains untracked
runtime artifacts. Canonical roots have not been switched. Those conditions are
expected until the guarded cutover below and must not be described as ready.
The live-read-only probe used one shared trace ID, made no generation request,
created no cost event, and did not attempt the handshake without its URL/secret.
Graphify refresh was attempted but remains `NOT_RUN` because the local
`graphify` binary is not installed; Python and TypeScript architecture gates
passed independently.

### Read-only production snapshot (2026-07-15)

A direct read-only ThreadsDashboard query found all five regular Reel test posts
published once with Instagram IDs/permalinks and 33 real metric-history rows.
All five have real 1-hour-window evidence; two currently have 24-hour-window
evidence; none yet has a 72-hour-window row. No values were synthesized.

Those five posts have no `campaign_factory` metadata,
`campaign_factory_asset_id`, or generated-asset lineage. They use two reused
media objects that are not present in the canonical local asset inventory.
Campaign correctly refuses to learn from them instead of guessing lineage.
They therefore prove ThreadsDashboard publishing/metrics, but they do not count
toward the 10-post reconciled Creator OS gate.

Three recent Trial Reel attempts are failed with no Instagram identity or
metric history: one fail-closed metadata-intent mismatch, one generic Instagram
failure, and one explicit app/account feature rejection. Trial publishing is
not proven and no automatic retry is pending. The local Campaign measured-facts
ledger still contains only the earlier archived Trial Reel's real eligible
1-hour snapshot and has zero 24-hour or 72-hour snapshots.

## Guarded Cutover Order

1. Push, review, merge, and CI-verify Creator OS source. The compatible
   ThreadsDashboard handshake source is already merged; deployment proof is
   still separate.
2. Apply and verify the copy-only local state migration. Keep every original.
3. Promote the exact reviewed Creator OS SHA to the clean runtime checkout and
   verify every LaunchAgent path.
4. Deploy the ThreadsDashboard endpoint through its normal process, configure
   the machine-local handshake URL/secret, and run only
   `creator-os status --live-read-only`.
5. Observe one complete operating cycle before considering old-path removal.
6. Reconcile real posts and metrics; never synthesize a missing Meta row.

Actual state cutover, runtime promotion, production deployment, paid provider
generation, scheduling, publishing, and credential rotation require their own
explicit authorization. This source repair performs none of them.

## Deferred By Design

- OpenTelemetry traces: add only after runtime promotion is stable.
- Supabase Queues: pilot only after seven stable days and either multiple
  workers or more than 20 active accounts; never duplicate a QStash event.
- Wan2.1/Kling and MLX Whisper/WhisperX: isolated bakeoffs only, not runtime
  dependencies.
- Old databases and compatibility paths: remove only after the retention window
  and a complete verified operating cycle.

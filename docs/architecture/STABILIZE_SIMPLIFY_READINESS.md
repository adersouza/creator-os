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
- a precise Reel worker lineage contract that cannot masquerade as finalized
  Campaign lineage, plus a provider-free active-mode-to-ThreadsDashboard
  consumer seam test;
- fail-closed Trial account projection: denied and known-missing-scope accounts
  are blocked, unknown accounts require explicit operator-canary authorization,
  and autonomous planning selects only proven-eligible accounts;
- a truly read-only draft preview that creates no export/job/event/file and
  never contacts ThreadsDashboard;
- a report-only post-retention cleanup eligibility command with no deletion
  primitive and private backup/database permission enforcement.

Creator OS still has no scheduling or publishing command. ThreadsDashboard is
the sole approval, scheduling, publishing, and Instagram account authority.

## Evidence Ledger

| Surface | Current status | Evidence required for PASS |
|---|---|---|
| Source | PASS on integrated branch | `make verify` passed with supported Node 24: ContentForge 129, contracts 24 TypeScript + 54 Python, Core 16, Campaign 692, Reference 111, Reel 436, integration 76, and offline prompt regressions 3/3; contracts, lint, formatting, typing, architecture, and artifact gates passed |
| CI | PASS on PR #442 / merge `2f0617bd` | Python, architecture, contracts, hygiene, changes, and secret scan passed; JavaScript, CodeQL, Trivy, and SBOM were path-filtered skips rather than failures |
| Runtime | PASS | clean detached runtime and source exactly match; the code-bearing cutover baseline is `2f0617bd`, and the pinned LaunchAgent completed with exit 0 at `2026-07-15T21:40:11Z` against the canonical database |
| Canonical state | PASS | migration manifest `~/.creator-os/backups/state-migrations/20260715T212851Z/migration-manifest.json` verified integrity, row counts, private modes, artifact hashes, and clean SQLite restores; machine envs switched; local backup snapshot `20260715_173212` passed |
| ThreadsDashboard seam | PASS live read-only | valid production HMAC/contract request passed with nonce claimed and `productRowsWritten=0`; invalid/stale/replay behavior remains covered by regression tests |
| Providers | PASS live read-only | account, selected workspace, Soul/Kling/Seedance availability, balance, and a 0.12-credit quote passed with zero media and zero cost events; no paid smoke was run |
| Publishing | Unchanged and out of scope for this source repair | existing ThreadsDashboard production evidence; Creator OS must remain unable to publish |
| Measured learning | NOT_PROVEN | post-promotion sync has one eligible post with a real 1h row, zero with 24h, zero with both, and one completed Reference fanout; exact 24h/72h evidence is still missing |
| Operational cohort | NOT_PROVEN | 10 consecutive correctly reconciled posts |
| Autonomous learning promotion | BLOCKED by evidence gate | 50 eligible posts with both real 1h and 24h measurements |

The runtime and canonical roots are now cut over, but old databases and paths
remain preserved as rollback evidence through at least 2026-07-22 and one
complete operating cycle. They must not be deleted before that retention gate.
The cutover-time `migrate_runtime_state.py --verify` command compares frozen
row counts and is not a post-cutover cleanup gate after legitimate live writes.
Use `scripts/runtime_state_cleanup_eligibility.py` with a fresh
`backup_runtime_state.py` manifest and explicit operating-cycle evidence. The
eligibility command accepts honest canonical database drift, requires private
SQLite/backup permissions plus clean restores and zero active old-path
references, and only reports candidates; it cannot delete anything.

The required operating-cycle evidence is a private JSON file with this shape:

```json
{
  "schema": "creator_os.operating_cycle_evidence.v1",
  "status": "PASS",
  "completedAt": "<timezone-aware timestamp after cutover>",
  "checks": {
    "runtimeShaMatched": true,
    "performanceSyncSucceeded": true,
    "learningFanoutObserved": true
  }
}
```

After producing a fresh `scripts/backup_runtime_state.py` backup, run:

```bash
uv run python scripts/runtime_state_cleanup_eligibility.py \
  --manifest <migration-manifest.json> \
  --operating-cycle-evidence <operating-cycle-evidence.json> \
  --backup-dir <fresh-backup-directory>
```

An `ELIGIBLE` report is still not deletion authorization.
The live-read-only probe used one shared trace ID, made no generation request,
created no cost event, and wrote no ThreadsDashboard product rows.
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

The current read-only account snapshot contains 208 Instagram accounts, 197
active. Trial capability evidence is 0 eligible, 2 denied, and 206 unknown, with
no stored OAuth-grant evidence yet. The local Creator OS roster maps 66 active
accounts: 2 denied and 64 unknown. This is why Trial automation must remain
closed. After source merge and exact runtime promotion, the normal account sync
must project those fields locally; operators may then reconnect accounts and
run bounded canaries one account at a time. Unknown is not eligibility.

## Guarded Cutover Order

1. **Complete:** merge and CI-verify Creator OS source.
2. **Complete:** apply and verify the copy-only local state migration while
   retaining every original.
3. **Complete:** promote the exact reviewed SHA to the clean runtime checkout
   and verify the LaunchAgent paths.
4. **Complete:** run the deployed zero-write handshake plus provider probes.
5. **Complete:** observe one successful post-promotion performance/learning
   operating cycle. Keep old paths until the separate seven-day retention gate.
6. **In progress:** reconcile real posts and 24h/72h metrics; never synthesize a
   missing Meta row.

Paid provider generation, scheduling, publishing, credential rotation, and
old-path deletion remain separately gated. This cutover performed none of them.

## Deferred By Design

- OpenTelemetry traces: add only after runtime promotion is stable.
- Supabase Queues: pilot only after seven stable days and either multiple
  workers or more than 20 active accounts; never duplicate a QStash event.
- Wan2.1/Kling and MLX Whisper/WhisperX: isolated bakeoffs only, not runtime
  dependencies.
- Old databases and compatibility paths: remove only after the retention window
  and a complete verified operating cycle.

# Creator OS Target-State Progress and Operational Truth Audit

> Snapshot: `2026-07-24T09:43:36Z`.
>
> This is a point-in-time evidence report. It is not the architecture authority,
> a deployment instruction, or permission to generate, schedule, publish, call a
> paid provider, or mutate production. Component ownership belongs in
> [`CREATOR_OS_SYSTEM_MAP.md`](./CREATOR_OS_SYSTEM_MAP.md). Volatile facts in
> this report must be refreshed before an operational decision.
>
> The audited baseline is the exact `origin/main` SHA recorded below, before
> this documentation-only branch. This report does not claim that its own
> documentation commit has been merged or promoted.

## Executive verdict

Creator OS now has the intended source architecture and its guarded runtime
promotion path is operational. The exact `main` commit is running in the clean
detached runtime, required CI and security checks passed, and the nine-check
live read-only health policy passed without provider jobs or product-row writes.

The local-video decision loop is not operationally complete. Five local video
models are installed and shallow-ready, Wan 5B has four genuinely distinct
outputs, and LTX Q4 has one fast generated-audio output. There are still zero
permanent benchmark receipts, zero model-promotion events, zero real Router
decision artifacts, zero authenticated would-post decisions for these outputs,
and no single modern asset proved through Router, approval, Instagram
publication, equal-age metrics, Campaign performance, and Reference learning.

The correct next phase is operational evidence, not another architecture
expansion.

## 1. Exact state

| Evidence | Current result |
|---|---|
| `origin/main` | `f1f12442720c6345b9099e5b071b26c3855b994d` |
| Runtime SHA | `f1f12442720c6345b9099e5b071b26c3855b994d` |
| Source/runtime identical | **Yes** |
| Runtime checkout | Clean, detached |
| Merge evidence | PR #508 merged to the exact SHA above |
| PR checks | **11 passed, 0 failed** |
| Main CI | Creator OS Monorepo CI passed for the exact SHA |
| Main security | Security and OpenSSF Scorecard passed for the exact SHA |
| Latest promotion | `00351135-17d1-4050-9861-06586187b717` |
| Promotion status | `promoted`; `rolledBack=false` |
| Promotion safety | `providerCalls=0`; `productionStateWrites=0` |
| Live health | **9 PASS, 0 WARN, 0 FAIL** |
| Health policy | `creator_os.runtime_live_read_only_health.v1` |
| ThreadsDashboard seam | HMAC draft-only handshake passed; scheduling and publishing disallowed; product rows written `0` |

Primary receipts:

- Runtime promotion:
  `~/.creator-os/state/runtime_promotions/receipts/00351135-17d1-4050-9861-06586187b717.json`
- Live status command:
  `/Users/aderdesouza/Developer/creator-os-runtime/scripts/creator-os status --live-read-only --json`
- GitHub evidence: PR #508 and main workflow runs for the exact SHA.

This proves source, runtime, and read-only seams. It does not prove a content
generation, draft, schedule, Instagram post, notification, or metric row.

## 2. Model reality

The append-only local generation journal was evaluated without counting
multiple successful executions of identical bytes as independent outputs:

`~/.creator-os/state/reel_factory/local_generation/jobs.jsonl`

| Model | Successful jobs | Unique outputs | Real failures | Average successful wall time | Peak memory observed | Technical QC | Identity QC | Authenticated would-post | Approved yield | Classification |
|---|---:|---:|---:|---:|---:|---|---|---:|---:|---|
| Wan 2.2 TI2V-5B MLX Q8 | 6 | 4 | 1 | 2,133.27 s | 8,202,764,288 B | NOT PROVED across the cohort | NOT PROVED across the cohort | 0 | 0 | **Viable benchmark candidate** |
| Wan 2.2 I2V-A14B MLX Q4 | 0 | 0 | 2 | N/A | 17,117,970,432 B | NOT PROVED | NOT PROVED | 0 | 0 | **Blocked** |
| LTX-2.3 distilled MLX Q4 | 1 | 1 | 0 | 208.27 s | 14,571,864,064 B | Trusted analysis exists; final publishability QC NOT PROVED | **Failed**: `0.025334 < 0.42` | 0 | 0 | **Experimental** |
| LTX-2.3 dev/HQ MLX Q8 | 0 | 0 | 0 | N/A | N/A | NOT PROVED | NOT PROVED | 0 | 0 | **Experimental, unexecuted** |
| LongCat Avatar 1.5 MLX Q4 | 0 | 0 | 2 | N/A | 23,607,803,904 B | NOT PROVED | NOT PROVED | 0 | 0 | **Blocked** |

All five report `ready=true` in shallow model status, but that means the
declared files and pinned runtimes are present. The status run did not use
`--deep`, so it reported `deepVerified=false`. Installed or shallow-ready is
not promoted.

Supporting local model:

- Qwen2.5-VL 7B 4-bit is the pinned Wan prompt-expansion preprocessor. It is not
  a sixth video generator and must not be counted as one.

Evidence:

- Wan four-seed run:
  `~/.creator-os/runs/wan_seed_uniqueness_20260723/`
- LTX Q4 qualification:
  `~/.creator-os/runs/ltx_q4_qualification_20260724/`
- Local model status:
  `creator-os advanced models status`

## 3. Arena results

There is no valid candidate-versus-baseline promotion comparison yet.

| Creator | Passive selfie | Lifestyle/full-body | Talking | Identity preservation | Fastest approved output | Highest approved yield |
|---|---|---|---|---|---|---|
| Stacey | Wan 5B produced four distinct outputs; no completed matched baseline or authenticated review | NOT PROVED | NOT PROVED | No model has an approved identity cohort | NONE | NONE |
| Larissa | NOT PROVED | NOT PROVED | NOT PROVED | NOT PROVED | NONE | NONE |
| Lola | NOT PROVED | NOT PROVED | NOT PROVED | NOT PROVED | NONE | NONE |

The Wan microcohort proves seed independence and early duplicate detection. It
does not prove quality, creator-specific superiority, approved yield, or a
promotion.

## 4. Model promotions

`creator-os advanced benchmarks status` returned:

```json
{
  "benchmarks": [],
  "promotionEvents": []
}
```

Therefore there are **no real permanent model promotions** to list. Runtime
promotion is healthy, but it is a different authority: it promotes reviewed
source code to the detached runtime, not a model to an intent cohort.

## 5. Router

No persisted `reel_factory.local_model_router_decision.v1` artifact was found
under canonical Creator OS state or run evidence. No selected model can yet be
shown as both evidence-selected and actually executed.

Router v1 is implemented and fail-closed. Operational routing is not proved
because it has no permanent benchmark/promotion evidence to consume.

## 6. Newest modern end-to-end trace

The newest useful single-asset trace is the LTX Q4 Stacey qualification output:

| Stage | Evidence for this exact asset |
|---|---|
| Creator | Stacey |
| `CreatorIdentityProfileV1` | `creator_profile_stacey_8102d78f5f93eb2f9333a3b6` |
| `ContentIntentV1` | `content_intent_06ee7f5c169d7e85642b7532` |
| Model Router | **NOT PROVED** |
| Generation job | `local_video_39d334d72ecea849c7d4a080` |
| Model | `local_ltx23_distilled_mlx` |
| Output SHA-256 | `094aead4407a28f75f478e6f533eb78cfb5df5ec877cb3406c51222a4f83f908` |
| Trusted analysis | `~/.creator-os/runs/ltx_q4_qualification_20260724/trusted_analysis.json` |
| Identity QC | Blocked; score `0.025334`, threshold `0.42` |
| Authenticated human review | **NOT PROVED** |
| Final motion QC | **NOT PROVED** |
| Creative Approval v2 | **NOT PROVED** |
| Exact draft | **NOT PROVED** |
| ThreadsDashboard ingest | **NOT PROVED** |
| Schedule | **NOT PROVED** |
| Instagram publication/media ID | **NOT PROVED** |
| 1h / 24h / 72h metrics | **NOT PROVED** |
| Campaign performance snapshot | **NOT PROVED** |
| Reference learning | **NOT PROVED** |

The trace correctly stops at failed identity evidence. Nothing from a different
asset is substituted to make the chain look complete.

## 7. Operator simplicity

The current local-motion command shape is:

```bash
creator-os create \
  --mode local_wan \
  --campaign <campaign> \
  --target stacey \
  --accepted-still <source-image> \
  --motion-task image_to_video \
  --motion-prompt "<motion intent>" \
  --local-evidence-bundle <bundle.json> \
  --local-arena-summary <summary.json> \
  --count 20 \
  --apply
```

This is not yet the honest minimum command for producing 20 local Reels:

- `--count` is accepted by the root CLI but the ordinary local-motion branch
  currently executes one motion stage; it does not prove creation of 20
  independent local queue jobs.
- The operator still supplies the exact source path, evidence bundle, and Arena
  summary path.
- Benchmark IDs, analyzer registries, model manifests, promotions, and model
  files are mostly nested or resolved behind those artifacts, but the operator
  still has to know where the artifacts live.

The desired operator command remains:

```bash
creator-os create \
  --mode local_wan \
  --campaign stacey \
  --intent passive_selfie \
  --count 20 \
  --apply
```

Campaign Factory should internally resolve the active identity profile,
approved source inventory, intent, active promotion, Arena evidence, analyzer
registry, model manifest, deterministic seeds/jobs, and output destinations.
Until then, simplification is incomplete.

## 8. Human work

| Lifecycle stage | Classification | Current reason |
|---|---|---|
| Reference intake | Exception-only human | Collection can be automated; rights/source exceptions need review |
| Gold/Maybe/Ignore taste labels | Human required | These define the creator's actual taste |
| Content intent and mode authorization | Human required | The operator selects intent, mode, paid authority, and risk |
| Source selection | Human required today | Automatic safe inventory resolution is not yet the normal local-motion path |
| Model installation/deep verification | Exception-only human | Setup and license decisions are operator-owned; verification is automatic |
| Router selection | Fully automatic when evidence exists | Currently blocked by zero promotions |
| Generation and queue recovery | Fully automatic | Failures remain evidence; no manual output rewriting |
| Technical/identity/duplicate QC | Fully automatic | Missing or failed evidence blocks |
| Would-post creative review | Human required | No authenticated approval exists yet for the local outputs |
| Creative Approval v2 | Human required | Binds the accepted Creator OS asset and export projection |
| Draft export | Human required today | Explicit `--apply`; Creator OS remains draft-only |
| ThreadsDashboard creative approval | Human required today | This duplicates some Creator OS approval work |
| Scheduling/publishing | Human or policy-driven in ThreadsDashboard | External production authority |
| Metric ingestion | Fully automatic after real rows exist | Missing observations remain missing |
| Learning update | Fully automatic after genuine metrics | No zero synthesis |

The double-approval issue remains real. The intended simplification is one
authoritative Creator OS creative approval, with ThreadsDashboard requiring
human action only for account, policy, audio, or health exceptions. That
production behavior has not been proved.

## 9. Current bottlenecks

For a request of 100 approved local Reels, the first likely bottleneck is
**approved creative yield**, because current authenticated approved yield is
zero.

Ranked:

1. **Human-approved yield:** no authenticated would-post receipts for the
   current local outputs.
2. **Promotion-backed routing:** zero permanent benchmark receipts and zero
   model promotions.
3. **Generation throughput:** Wan 5B averages about 35.6 minutes per successful
   job. LTX Q4 is about 3.5 minutes but failed identity QC.
4. **Batch orchestration:** the normal `--count 20` local path is not proved to
   fan out 20 independent jobs.
5. **Closed-loop evidence:** no current Router-selected asset has publication
   identity plus 1h/24h/72h metrics and learning closure.

## 10. Keep, demote, or remove from active routing

This is a recommendation. Do not delete model files or evidence.

| Model/path | Recommendation | Reason |
|---|---|---|
| Wan 2.2 TI2V-5B MLX Q8 | **KEEP as viable candidate** | Four distinct real outputs; quality recipe needs stronger primary motion and authenticated review |
| LTX-2.3 distilled MLX Q4 | **EXPERIMENTAL** | Fast real run with generated audio, but failed identity badly |
| LTX-2.3 dev/HQ MLX Q8 | **EXPERIMENTAL** | Installed and capable on paper; no real execution |
| Wan 2.2 I2V-A14B MLX Q4 | **DEMOTE from active routing** | Two failures, zero outputs; allow one bounded future diagnostic, not normal routing |
| LongCat Avatar 1.5 MLX Q4 | **DEMOTE from active routing** | Two failures, zero outputs; talking capability remains unproved |
| Qwen-VL Wan prompt expander | **KEEP as support capability** | Correctly addresses under-specified blink-only prompts; not a video model |
| Paid `best_motion` providers | **KEEP behind explicit paid authority** | Separate fallback/quality lane; no silent local-to-paid fallback |
| Retired local-motion aliases and legacy grid paths | **KEEP RETIRED** | Historical replay only; do not restore to the operator surface |

No model should be labeled `PROMOTE` until it wins a valid matched cohort with
complete QC and authenticated blind human evidence.

## 11. Ten-account pilot

A supervised ten-account pilot is **not ready to design as an executable
operation** because the required continuous canary does not exist.

The preconditions are:

1. Two viable models produce distinct outputs on a shared matched recipe.
2. Authenticated blind review establishes non-zero would-post yield.
3. One model receives a real scoped promotion.
4. Router selects it without an override and the exact selected model executes.
5. One exact asset completes Creative Approval v2, draft handoff, Instagram
   publication, 1h/24h/72h metrics, Campaign performance, and Reference
   learning.
6. The ordinary command creates a real batch without operator-supplied internal
   evidence paths.

Only after those gates should a pilot specify accounts, frequency, content mix,
review load, success thresholds, account-restriction monitoring, and equal-age
metric coverage.

## 12. Strategic simplification status

The external critique's core recommendation has been adopted in the durable
mental model:

```text
Intelligence
  -> Orchestrator
  -> Content engine
  -> Distribution
  -> real outcomes
  -> Intelligence
```

What has materially simplified:

- one supported root operator CLI;
- one Campaign control plane;
- one SQLite local generation queue;
- generated Pipeline Contract consumers instead of copied schema trees;
- direct headless ContentForge QC instead of another daemon;
- retired Grok grid/panel production paths and legacy motion aliases;
- explicit Creator OS versus ThreadsDashboard ownership;
- one guarded source-to-runtime promotion command;
- four truth levels that prevent merged code from being called production proof.

What is still too complex for the operator:

- local motion requires internal evidence-file paths;
- `--count` does not yet prove real local fan-out;
- Campaign and ThreadsDashboard both have human approval points;
- model qualification exposes Arena/benchmark machinery before any model is
  promoted;
- no single command resolves creator, source inventory, promotion, routing, QC,
  approval, and batch output.

The next simplification should remove operator decisions from the golden path.
It should not remove lineage, contracts, QC, authentication, spend authority,
or the Creator OS/ThreadsDashboard boundary.

## Final verdict

| Question | Answer |
|---|---|
| Is the target architecture implemented? | **Mostly yes** |
| Is the guarded source/runtime system operational? | **Yes** |
| Is local model routing genuinely evidence-based in real use? | **No** |
| Is the operator workflow genuinely simple? | **Not yet** |
| Is one modern closed loop proved? | **No** |
| Are we ready for a supervised ten-account pilot? | **No** |

The five most important remaining tasks are:

1. Complete authenticated human review of the four distinct Wan outputs.
2. Repair the LTX identity recipe and prove a four-seed distinct microcohort.
3. Run one valid matched Arena comparison and create the first scoped model
   promotion.
4. Execute one normal, non-override Router decision and make `--count` fan out a
   real batch while resolving evidence internally.
5. Carry one Router-selected asset through approval, ThreadsDashboard,
   Instagram, equal-age metrics, Campaign performance, and Reference learning.

That is the shortest path from a strong architecture to a real operating
system.

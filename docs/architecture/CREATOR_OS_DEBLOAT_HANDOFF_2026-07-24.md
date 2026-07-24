# Creator OS Debloat Handoff

Date: 2026-07-24
Baseline: `origin/main` at `ae165a4164ab0d420f74b83415c5cd4599f85f53`

This is a cleanup handoff, not a new architecture proposal. The next operator
goal is to prove that Creator OS can make postable creator videos quickly and
cheaply. Code, rules, tests, contracts, and runtime machinery that do not
materially support that goal should not remain on the active path.

## Locked Product Direction

### Now

Use WaveSpeed Wan 2.2 I2V 5B to:

1. finish prompt testing quickly;
2. generate real content batches;
3. prove postable quality.

The intended WaveSpeed provider model is:

```text
wavespeed-ai/wan-2.2/i2v-5b-720p
```

The current Creator OS catalog does not contain this endpoint. It currently
contains WaveSpeed Wan 2.7 image/reference models and Wan 2.2
speech-to-video. Reuse the existing fail-closed WaveSpeed upload, one-submit,
poll, download, spend-cap, and receipt behavior. Do not build another provider
framework.

### Parallel, using existing free credits

Use Modal monthly credits to build one minimal CUDA Wan worker. Benchmark it
against WaveSpeed using the same approved image, prompt, and seed. Record:

- would-post rate;
- identity resemblance;
- motion naturalness;
- face stability;
- wall time;
- provider or compute cost;
- failures;
- cost per accepted clip.

### Later

Evaluate Vast.ai or RunPod only if the Modal benchmark shows that self-hosted
CUDA Wan measurably beats WaveSpeed on accepted-output cost, speed, or quality.
Do not add those providers speculatively.

## Measured Bloat Snapshot

A read-only static scan of this baseline found:

| Surface | Count |
|---|---:|
| Non-test source lines, including generated TypeScript | about 192,600 |
| Test definitions/cases found by static scan | about 2,022 |
| Pipeline Contract schemas | 56 |
| `CREATE TABLE` occurrences across Python packages | 117 |
| Campaign Factory parser subcommands | about 284 |
| Obvious later/evaluation production code | at least 73,000 lines |

The last row includes the local model evaluation/release laboratory plus clear
later-stage Campaign/Reference/ContentForge areas. It is a conservative floor,
not a claim that every other line is necessary.

The current repository is overbuilt for the immediate product goal. A
defensible 38 percent of production source is already outside the immediate
path. A caller/runtime audit is expected to show that roughly 50–65 percent can
be deleted or archived, while 60–75 percent can be removed from the operator
critical path.

## Minimal Active Path

Keep the operator path this small:

```text
approved source
  -> prompt + seed
  -> WaveSpeed Wan 5B
  -> basic media and identity checks
  -> simple human would-post review
  -> approved draft
  -> ThreadsDashboard
  -> real metrics later
```

The parallel Modal worker is an implementation benchmark, not a second control
plane.

## Rules Worth Keeping

Retain only the rules that prevent irreversible cost, duplicate provider work,
wrong-account publication, or false evidence:

1. Paid generation requires an explicit cap and exact request scope.
2. Never blindly retry an ambiguous provider submission.
3. Preserve source SHA, prompt, seed, provider receipt, output SHA, wall time,
   and cost.
4. Require a human would-post and identity decision before draft approval.
5. Require exact account and draft approval before publishing.
6. Never synthesize publication identities or performance metrics.

Everything else must justify its continued presence against the immediate
postable-content goal.

Keep the Creator OS and ThreadsDashboard repositories separate. Creator OS
owns creation, evidence, and draft preparation. ThreadsDashboard owns accounts,
OAuth, scheduling, publishing, and real platform outcomes.

## Local Machine Cleanup Already Completed

This work was machine-local and is not represented by a Git diff.

Permanently removed after resolving failure evidence and live process usage:

| Removed target | Former size | Failure evidence |
|---|---:|---|
| `Wan2.2-I2V-A14B-MLX-Q4` | 27 GB | two failures, zero outputs |
| `LTX-2.3-MLX-Q4` | 19 GB | output failed identity QC |
| `LongCat-Video-Avatar-1.5-q4-dmd-merged` | 23 GB | two failures, zero outputs |
| `longcat-avatar-mlx` runtime | 617 MB | dedicated to deleted LongCat model |

Approximately 70 GB was reclaimed. Generation journals and run evidence were
preserved.

Retained deliberately:

- Wan 2.2 TI2V-5B MLX Q8, used by the active prompt A/B run;
- Qwen2.5-VL prompt expander;
- `mlx-video` and `mlx-vlm` runtimes;
- LTX-2.3 MLX Q8 because it is untested rather than proven failed;
- the LTX shared Gemma model and runtime required by retained LTX Q8;
- all source images, outputs, receipts, reviews, and historical evidence.

Do not reinstall the deleted models unless a new bounded experiment has a
specific product reason and explicit operator approval.

## Cleanup Slices

Execute cleanup in an isolated worktree after the active audio task has
finished. Preserve dirty developer checkouts and machine-local evidence.

### 1. Remove failed models from active source surfaces

- Remove the deleted A14B Q4, LTX distilled Q4, and LongCat Q4 models from the
  selectable model catalog and normal readiness output.
- Preserve the ability to read their historical receipt/model identifiers.
- Remove model-specific installation and routing branches that have no retained
  caller.
- Do not remove Wan 5B, Qwen, or untested LTX Q8 in this slice.

### 2. Collapse local qualification into a small experiment harness

Remove Arena, Router, and model-promotion ceremony from normal content
generation. The existing implementation currently spans large modules for
Arena planning/review/unblinding, benchmark promotion, routing, model
management, and runtime promotion.

Retain only enough experimental tooling to:

- bind image, prompt, seed, settings, output SHA, time, memory, and cost;
- produce a simple blinded A/B board when useful;
- record human would-post and identity judgments;
- compare successful accepted-output yield.

Historical receipts remain evidence. They do not require the entire promotion
system to remain active.

### 3. Reduce Campaign Factory to current work

Keep:

- creator/source selection;
- batch generation request;
- paid spend cap;
- output registration;
- simple approval;
- validated ThreadsDashboard draft handoff;
- genuine metric ingestion when real metrics exist.

Delete or archive current no-evidence scale machinery, including dormant or
unproved recommendation, certification, readiness-reporting, parent-factory,
account-memory, autonomous-learning, content-graph, and large-scale inventory
surfaces when caller analysis confirms they are not on the retained path.

The root command should expose a small operator vocabulary. Hundreds of hidden
Campaign developer subcommands are not an acceptable substitute for
simplicity.

Prefer content intents such as `static`, `motion`, `talking`, `remix`, and
`reuse` over provider-specific operator concepts. Provider choice is execution
policy and may change without changing what the operator is trying to create.

Do not introduce another service layer merely to hide the existing services.
Converge on a small set of real use cases such as create batch, review batch,
approve, export, sync, and status.

When cleanup touches Campaign Factory typing debt, do not launch a standalone
typing rewrite. Require touched modules to introduce no new errors and reduce
existing errors where practical.

### 4. Freeze Reference Factory to approved-source support

Keep the approved creator/source inventory and any proven prompt/reference
knowledge used by generation. Make measured learning dormant until genuine
Instagram publication and metric history exist.

Delete or archive uncalled server, analysis-provider, pattern, learning, and
public-metrics surfaces that do not support the retained source manifest or
real metric ingestion.

### 5. Make ContentForge small and optional

Keep:

- readable video/FFprobe checks;
- basic duration/dimension validation;
- exact duplicate detection;
- minimal identity/face review support.

Move advanced forensics, variation packs, editorial derivatives, virality
gates, and campaign audit/reporting off the mandatory prompt-testing path.
Delete callerless code rather than preserving compatibility indefinitely.

There should be one authoritative creative approval. Avoid mandatory duplicate
human review in both Creator OS and ThreadsDashboard; downstream review should
be exception-based for account, policy, health, or low-confidence cases.

### 6. Reduce contracts and state

Define the few durable boundaries required by the minimal path:

- generation request and receipt;
- human review;
- approval;
- draft payload;
- audio intent if used;
- real metric observation.

Remove obsolete schema versions only after retained producer/consumer searches
and focused fixture migration. Do not create replacement schema layers.

Do not delete machine databases merely because their source table is retired.
Database/evidence deletion remains separate from source cleanup.

### 7. Replace rule sprawl with one short operating contract

Reduce overlapping architecture documents and agent rules to:

- the minimal active path;
- the six retained safety rules above;
- exact source/runtime/provider truth when it matters;
- the boundary that ThreadsDashboard alone schedules and publishes.

Historical reports should be clearly archived and must not dictate new
operator work.

Stop building synthetic 1,000–10,000-account readiness machinery. Prove the
workflow at real 10, 25, 50, 100, and 200-account stages using measured
generation yield, human review time, cost, uniqueness, handoff reliability,
publication failures, and metric-sync success.

## Explicit Non-Targets

The cleanup must not:

- schedule or publish;
- write production rows;
- modify ThreadsDashboard production behavior;
- delete source images, completed outputs, receipts, or real metrics;
- interrupt active audio or Wan jobs;
- add providers beyond WaveSpeed 5B and the bounded Modal benchmark;
- create a new orchestration framework;
- promote a model from a tiny cohort;
- reintroduce deleted local models through an install-all command.

## Acceptance

The cleanup is successful when:

1. one simple command can launch a bounded WaveSpeed Wan 5B prompt test or
   content batch;
2. every result preserves the small receipt set defined above;
3. a reviewer can quickly mark would-post and identity quality;
4. approved outputs can become validated ThreadsDashboard drafts;
5. no scheduling, publication, or production metric fabrication is possible;
6. the retained focused tests pass;
7. final repository-wide verification passes once after the deletion slices;
8. the operator no longer needs Arena, Router, promotions, analyzer registries,
   or hundreds of Campaign subcommands to make a Reel.

Delete aggressively, but prove each deletion against the retained path. Git
history is the archive; dead runtime compatibility does not need to remain in
the active tree.

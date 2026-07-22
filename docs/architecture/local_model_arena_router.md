# Local Model Arena And Router v1

## Purpose

The Arena answers a narrow question: which installed local model configuration
is useful for one creator intent on this machine? It does not schedule work or
replace Campaign Factory. Generation still uses `LocalGenerationQueue`; timing,
memory, QC, and promotion still use `LocalModelBenchmarkStore`.

## Frozen plan

Every plan records exact creator/intent fingerprints, source and optional audio
SHA-256 values, prompt, seed, duration, resolution, model revision and manifest,
output path, queue-job fingerprint, benchmark recipe, analyzer registry, blind
candidate ID, and the planned denominator. Promotion-eligible designs require
Stacey, Larissa, and Lola, at least two safe sources per creator/model/intent
cohort, and at least two seeds per source. Smaller runs are explicitly
exploratory.

Supported terminal classes are `succeeded`, `failed`, `interrupted`,
`resource_blocked`, `unsupported`, and `missing`. There is no implicit retry or
sample replacement. Interrupted queue jobs use the existing explicit queue
recovery command and retain their original evidence.

Queue evidence distinguishes an admission block from a real execution attempt.
Every sample summary carries attempt count, retry count, admission-block count,
stable failure class, measured duration/peak memory when available, and an
explicit local-cost observation. Local compute cost remains unavailable until a
real meter exists; it is never represented as zero.

## Evidence production

ContentForge samples the actual output with FFprobe/FFmpeg and produces raw
observations separately from verdicts. Missing audio, overlays, identity,
anatomy, or lip-sync are unavailable/not-applicable, never numeric zero. Exact
per-analyzer receipts, automated identity evidence, structured human review,
and final motion QC are copied into benchmark evidence by SHA-256. Changed
media, code, registry, recipe, queue job, or receipt fails closed.

Structured review captures reviewer, timestamp, rubric version, blinded ID,
source/output hashes, realism, attractiveness, resemblance, face stability,
motion naturalness, anatomy/artifact scores, intent adherence, conversion
usefulness, and explicit decisions. It is required for promotion; it is not
invented by automation.

Dedicated lip-sync is not yet a trusted pinned analyzer. Source/generated audio
technical integrity is measurable, but talking/avatar promotion remains
blocked when lip-sync is required.

## Router v1

Router input is a creator identity, content intent, required task/capability,
resource budget, exact Arena summary, benchmark store, and active promotion
state. Candidate exclusion reasons are machine-readable. Selection is
deterministic and quality-first: human quality and valid yield dominate, with
smaller latency/resource tie-breakers.

The Router rejects:

- paid, missing, unready, drifted, stale, or unapproved models;
- capability/task mismatch;
- insufficient memory;
- historical receipts without recipe/registry linkage;
- missing/failed QC or human quality;
- expired or revoked promotions.

Overrides may choose only an otherwise valid candidate. The decision records
the operator and reason and excludes that choice from benchmark learning.

## Commands

```bash
scripts/creator-os advanced analyzers
scripts/creator-os advanced arena --root <evidence-root> plan ...
scripts/creator-os advanced arena --root <evidence-root> generate \
  --plan-id <id> --sample-id <id> --mode local_wan --dry-run
scripts/creator-os advanced arena --root <evidence-root> finalize ...
scripts/creator-os advanced arena --root <evidence-root> summary --plan-id <id>
scripts/creator-os advanced router --request <json> --arena-summary <json>
```

No command above schedules, publishes, downloads a model, or permits a provider
fallback.

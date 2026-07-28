# Creator OS Bloat Inventory

> **Historical input to the completed simplification work.** Dispositions and
> size/timing observations below are not a current backlog or runtime policy.
> The reconciled architecture is in
> [`CREATOR_OS_SYSTEM_MAP.md`](./CREATOR_OS_SYSTEM_MAP.md), and current measured
> weight is in [`PIPELINE_STATE.md`](./PIPELINE_STATE.md).

Scope: live `creator-os/main` and `ThreadsDashboard/main` call sites inspected
2026-07-24. Times are measured or workflow-time estimates; “caught” is based on
repository tests, comments, receipts, and incident docs—not assumed value.

| Item | Protects / actual caller | Where and cadence | Cost / caught real failure | Overlap or production friction | Disposition |
|---|---|---|---|---|---|
| Changed-file syntax, Ruff, format | Python edit correctness | local, each edit | seconds; yes | none | KEEP_IN_HOT_PATH |
| Focused unit tests | changed behavior | local, each edit | seconds-minutes; yes | replaces full-suite habit | KEEP_IN_HOT_PATH |
| Full `make verify` on every edit | all repository behavior | local, informal | 10+ min; yes, but mostly unrelated | duplicates CI/release | SIMPLIFY |
| Affected package tests | package behavior | PR | target <10 min; yes | previously hidden inside full matrix | MOVE_TO_TARGETED_PR_CHECK |
| Contract generation drift | cross-repo payload compatibility | schema PR and release | <1 min; yes | unrelated on most edits | MOVE_TO_TARGETED_PR_CHECK |
| Full Python package matrix | release integrity | every PR and main | ~12 min hosted; yes | exact suite rerun | MOVE_TO_MAIN_CI |
| Full ContentForge lint/test/build | release integrity | every PR and main | ~10 min hosted; yes | unrelated to Python-only edits | MOVE_TO_MAIN_CI |
| Python/TS architecture graph checks | ownership boundaries | every PR | minutes; yes | broad and low-frequency failure | MOVE_TO_MAIN_CI |
| Architecture guard fixtures | guard implementation | every PR | minutes; no recent unique hot-path failure | weekly | MOVE_TO_NIGHTLY_OR_WEEKLY |
| Prompt regression corpus | prompt policy | every PR | minutes; useful prompt failures | unrelated to most changes | MOVE_TO_MAIN_CI |
| Current-tree secret scan | secrets | PR | <1 min; yes | external trust boundary | KEEP_AT_EXTERNAL_BOUNDARY |
| Full-history TruffleHog | historical secrets | every PR | minutes; yes | repeated full history | MOVE_TO_NIGHTLY_OR_WEEKLY |
| CodeQL Python and JS | static security | every PR | two hosted jobs; yes | release/security horizon | MOVE_TO_MAIN_CI |
| Trivy filesystem/license scan | dependency risk | every PR | hosted minutes; yes | release/security horizon | MOVE_TO_NIGHTLY_OR_WEEKLY |
| SBOM + attestation | release provenance | main | hosted minutes; no local role | correct boundary | MOVE_TO_MAIN_CI |
| Scorecard | repository posture | scheduled | hosted minutes | no content-path role | MOVE_TO_NIGHTLY_OR_WEEKLY |
| Runtime promotion verification | exact runtime dependencies | promotion | expensive; caught PATH/toolchain drift | unique trust boundary | MOVE_TO_RUNTIME_PROMOTION |
| Provider spend authorization | prevents unauthorized paid call | immediately before paid call | negligible; yes | unique boundary | KEEP_AT_EXTERNAL_BOUNDARY |
| Source SHA at import/generation | source substitution | external input and request | negligible; yes | unique boundary | KEEP_AT_EXTERNAL_BOUNDARY |
| Output SHA at provider/worker result | changed/corrupt output | worker return and handoff | negligible; yes | unique boundary | KEEP_AT_EXTERNAL_BOUNDARY |
| Canonical duplicate-output SHA gate | false independent samples and duplicate assets | output registration | negligible; caught duplicate local generations | unique failure | KEEP_IN_HOT_PATH |
| Rehash immutable canonical output during internal reads | changed bytes | repeated internal functions | small per call | same content-addressed record | MERGE_WITH_DUPLICATE |
| Draft contract validation | forged/invalid handoff | Creator OS→ThreadsDashboard | small; yes | real boundary | KEEP_AT_EXTERNAL_BOUNDARY |
| Publish preflight and idempotency | invalid/duplicate publication | ThreadsDashboard publish request | small; yes | real boundary | KEEP_AT_EXTERNAL_BOUNDARY |
| Metrics timestamp/media identity checks | false learning | ThreadsDashboard→Creator OS | small; yes | real boundary | KEEP_AT_EXTERNAL_BOUNDARY |
| Missing metrics stay missing | false zero performance | learning ingestion | none; yes | core truth | KEEP_IN_HOT_PATH |
| Arena cohort requirement for automatic selection | model comparison integrity | research | hours/GPU; yes | correct only for comparison | RESEARCH_ONLY |
| Router evidence for automatic selection | evidence-based model choice | research/promotion | minutes plus receipts; yes | correct only for automatic choice | RESEARCH_ONLY |
| Arena/Router requirement for explicit pinned Wan | model choice | every local production call | paths + cohort prerequisite; blocks working model | no new failure beyond pinned recipe/runtime binding | DELETE |
| Analyzer registry in explicit production request | research QC reproducibility | every local call | evidence paths and reparsing | hard/soft production QC already follows output | RESEARCH_ONLY |
| Benchmark recipe in explicit production request | cohort comparability | every local call | evidence paths and reparsing | no production purpose | RESEARCH_ONLY |
| Local runtime/model capability probe | exact working runtime | each local worker call | seconds; caught missing runtime/model | unique execution boundary | KEEP_IN_HOT_PATH |
| Operator source path | source selection | every generation CLI | manual search and substitution risk | inventory already owns paths/hashes | DELETE |
| Operator seed | research reproducibility | every generation CLI | decision friction | batch planner can derive unique deterministic seed | RESEARCH_ONLY |
| Operator evidence/Arena/registry paths | research provenance | every generation CLI | severe friction and missing-path failures | internally research-owned | DELETE |
| Operator provider task/queue IDs | recovery | advanced CLIs | recovery-only | no normal creative intent | RESEARCH_ONLY |
| Operator runtime/model directory | runtime override | advanced CLIs | substitution risk | promoted runtime owns it | MOVE_TO_RUNTIME_PROMOTION |
| `generation run --mode ...` | explicit implementation control | developer CLI | dozens of flags | leaks implementation | RESEARCH_ONLY |
| `creator-os create` old alias to explicit-mode generation | compatibility | normal root CLI | exposed every internal flag | conflicts with intent-first product | DELETE |
| New intent-first `creator-os create` | creator, intent, count, execution, accounts, audio | normal production | six stable inputs | resolves implementation internally | KEEP_IN_HOT_PATH |
| `count` accepted by one motion call | batch semantics | generation workflow | misleading; one output | no fan-out | DELETE |
| Independent production batch planner | source, seed, request identity per item | normal production | negligible planning | makes count truthful | KEEP_IN_HOT_PATH |
| `make-batch` legacy import/render workflow | bulk library rendering | advanced compatibility | broad, many implementation args | different legacy semantics from creative jobs | ARCHIVE |
| Manual creative approval for calibration | recipe/QC calibration | Creator OS | reviewer time; useful early | should be sampled/exception-based | KEEP_IN_HOT_PATH |
| Mandatory human approval for every approved recipe output | subjective quality | every motion asset | dominant operator delay | hard QC + calibrated recipe already own decision | DELETE |
| ThreadsDashboard operator review on `review_only` drafts | explicit review batches | TD UI | reviewer time | useful calibration surface | KEEP_AT_EXTERNAL_BOUNDARY |
| ThreadsDashboard subjective reapproval for publishable Creator OS draft | subjective quality | not required by current ingest (`approval_status=null`) | none currently | would duplicate Creator OS | DELETE |
| ThreadsDashboard auth/account health/schedule restrictions | publication safety | schedule/publish | small; caught real failures | unique external owner | KEEP_AT_EXTERNAL_BOUNDARY |
| ContentForge corruption/readability/distinctness hard findings | unusable/unsafe media | before approval/handoff | seconds-minutes; yes | practical QC | KEEP_IN_HOT_PATH |
| Identity, corrupt face/body, codec, duration, audio hard blockers | postability | production QC | seconds-minutes; yes | unique failure classes | KEEP_IN_HOT_PATH |
| Attractiveness/motion/hook/aesthetic thresholds as blockers | taste/ranking | production QC | false rejection risk; no calibrated universal threshold | belongs in ranking/learning | SIMPLIFY |
| Soft scores retained as ranking features | candidate ordering | production | negligible | improves learning without blocking | KEEP_IN_HOT_PATH |
| `motion_edit` and `best_only_kling` operator aliases | historical replay | already absent from mode list | no normal caller | contracts/evidence still readable | ARCHIVE |
| `motion_edit_stage.py` tombstone | fail-closed old import | historical replay tests | negligible | compatibility only | ARCHIVE |
| `scripts/run_campaign_factory.sh` wrapper | legacy local startup | no source caller; docs only | extra entrypoint | canonical root CLI/service commands exist | ARCHIVE |
| Dated architecture/debloat/readiness reports | historical decisions | docs | navigation cost | repeat current map/status | ARCHIVE |
| `README.md`, system map, `PIPELINE_STATE.md` | normal use, durable map, current status | docs | low | distinct authorities | KEEP_IN_HOT_PATH |
| Campaign Factory SQLite + duplicated handoff metadata | local control and external projection | persistence/handoff | storage negligible | duplication required at trust boundary only | KEEP_AT_EXTERNAL_BOUNDARY |
| ThreadsDashboard Supabase post row | draft/schedule/publish source | external repo | required | not a duplicate internal production row | KEEP_AT_EXTERNAL_BOUNDARY |
| Queue idempotency/recovery doctors | crash/retry safety | runtime/recovery | periodic | should not run per creative edit | MOVE_TO_NIGHTLY_OR_WEEKLY |
| Historical schema replay/migration restoration | old data recovery | release/recovery | expensive | no normal creation role | MOVE_TO_NIGHTLY_OR_WEEKLY |

Estimated first-tranche savings:

- Local edit loop: full repository verification replaced by a measured focused
  suite (seconds instead of the broad 10+ minute path).
- Pull requests: three broad test/architecture jobs collapse into one
  change-aware package job; full release coverage remains on main.
- Explicit local Wan: removes four operator evidence inputs and the prerequisite
  Arena cohort/Router promotion.
- Batch creation: one intent command creates `N` independently identified jobs
  instead of accepting `N` while creating one.
- Approved production recipes: removes mandatory per-asset subjective review;
  calibration and exception review remain.

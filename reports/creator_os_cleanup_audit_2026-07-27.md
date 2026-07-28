# Creator OS Cleanup Audit — 2026-07-27

## Executive result

The audit started and ended with source and detached runtime at
`4035de1cf6141892cff2f2233beb32252d753e8a`. The source and runtime remained
clean. No provider, production database, creator source, audio catalog, media,
plan, learning, schedule, export, publication, or promotion mutation occurred.

Verified automatic cleanup removed 14 clean merged/ancestor-only worktrees, 13
merged local task branches, 12 merged remote task branches, ignored development
caches, and package-manager objects reported unused. Four open Dependabot PRs
were preserved.

The measured footprint fell by 31,143,585,915 logical bytes and 990,924 files.
Because the worktrees used APFS clone sharing, actual filesystem free space rose
by 3,432,222,720 bytes; the larger summed block-size delta is not presented as
real disk recovery.

## Starting truth

| Item | Starting state |
| --- | --- |
| Authoritative source | `4035de1cf6141892cff2f2233beb32252d753e8a` |
| Promoted runtime | `4035de1cf6141892cff2f2233beb32252d753e8a`, clean detached |
| Open PRs | #532, #533, #534, #535; all Dependabot |
| Worktrees | 16 |
| Local branches | 15 |
| Remote refs | 19 |
| Stashes | 0 |
| Logical footprint | 218,689,316,007 bytes |
| File count | 1,509,609 |
| Directory count | 224,853 |
| Available disk | 523,542,142,976 bytes |
| Git objects | 40.94 MiB packed plus 836 KiB loose |

The private inventory contains the requested top-100 largest-file and
largest-directory tables. The dominant retained categories are local advanced
model weights, creator/reference libraries, historical generation runs,
campaign artifacts, backups, the source environment, and the detached runtime.

## Retention classification

### SAFE_EPHEMERAL removed

- clean merged worktree copies and their per-worktree environments;
- Python bytecode, pytest, mypy, Ruff, Hypothesis, import-linter, Turbo, and
  editable-install caches outside the retained source environment;
- 50,919 pnpm cache files and 887 unused packages;
- npm cache garbage identified by `npm cache verify`.

`uv cache prune` found no unused package entries. Current source/runtime Python
environments and current source Node dependencies were retained.

### ACTIVE_OPERATIONAL retained

- four canonical SQLite databases and canonical private state;
- the detached promoted runtime;
- creator identities, Soul bindings, source inventory, campaign artifacts, and
  current schedules;
- 126 Audio Radar catalog rows, 17 active/resolved tracks, and all 25 playable
  cache objects;
- supported advanced local-generation models and their pinned manifests.

### HISTORICAL_EVIDENCE retained

- provider and spend receipts, WaveSpeed readers and records, paid bakeoff
  evidence, release/security evidence, rollback bundles, publication/export
  records, metric history, rejected-recipe evidence, and historical run output;
- 19 duplicate source-hash groups, because their metadata references are not
  disposable duplicates;
- missing historical file references, which remain missing evidence rather than
  silently deleted rows.

### UNKNOWN_OR_AMBIGUOUS retained

Ignored private media under source-local temporary directories, large archive
batches, historical mass-render output, and possible duplicate creator media
were retained. Their byte/reference graphs are incomplete, so neither age nor
filename qualifies them for deletion.

## Git and worktree hygiene

Every removed task worktree was clean, had zero untracked files, was unused by
active processes, and was associated with an exact merged PR head. The detached
benchmark parent was already reachable from main. The normal checkout and
production runtime were excluded.

Squash-merged branch tips are not ancestors of main by object identity, so
cleanup used the exact merged GitHub PR head and merge identities instead of a
false ancestry-only test. Open Dependabot branches were untouched.

Git history was not rewritten and Git objects were not forcibly pruned.
`git fsck` reported only ordinary dangling objects and no corruption. The
reachable commit graph was rebuilt and verified.

## Database and state audit

| Database | Tables | Indexes | Integrity | Foreign-key violations | Mutation |
| --- | ---: | ---: | --- | ---: | --- |
| Campaign | 74 | 237 | `ok` | 0 | None |
| Reference | 22 | 60 | `ok` | 0 | None |
| Reel manifest | 26 | 68 | `ok` | 0 | None |
| Render queue | 1 | 3 | `ok` | 0 | None |

Canonical database hashes were captured before cleanup and verified afterward.
No `VACUUM`, `ANALYZE`, migration, checkpoint, or write was performed.

The canonical reference graph currently records 881 sources, 736 rendered
assets, 736 generation attempts, 742 output blobs, 742 lineage edges, 172
exports, and one performance snapshot. Existing missing-path metadata was
retained: 3 source paths, 13 rendered paths, and 22 export manifests. These are
historical integrity findings, not cleanup deletions.

## Media and Audio Radar

No media bytes were removed. The reference audit found 878 present source paths,
723 present rendered paths, and 150 present export manifests. Nineteen duplicate
source-hash groups remain metadata/reference duplicates; there are no duplicate
rendered-hash groups.

Audio Radar remains unchanged:

- 126 catalog tracks;
- 31 resolved tracks, including 17 active/resolved;
- 25 cached/playable objects totaling 129,000,689 cataloged bytes;
- zero missing cached paths;
- zero duplicate cached byte-hash groups;
- zero duplicate acoustic-fingerprint groups;
- one exact selection and zero performance rollups.

No audio refresh or active prune workflow ran.

## Dependencies and active code

The Node workspace reports six production and seven development direct entries.
Knip found no unused direct dependency; its only findings were intentionally
invoked system binaries such as FFmpeg, FFprobe, fpcalc, Tesseract, and Swift.
`pnpm audit --prod` found no known vulnerabilities.

Python has 39 unique direct declarations across production, optional, and
development groups. One narrow classification defect was proven: root `pytest`
was declared as a production dependency despite having only test/release
consumers. A separate draft PR moves the same pinned version into the development
group with four lockfile-line changes and no version upgrade.

No code module met the complete deletion standard. Normal production reaches
Higgsfield only. WaveSpeed code is required for historical schemas, receipts,
approvals, and bakeoff readability. Local Wan/LTX, Arena, Router, analyzers, and
model management remain documented advanced paths. Status and plan-status
surfaces are complementary scopes rather than duplicate implementations.

Architecture checks covered 75 TypeScript modules/272 dependencies and 345
Python files/920 dependencies with zero violations.

## CLI and startup weight

The supported top-level CLI exposes 19 parser entries representing 17 canonical
commands plus the documented `review/readiness` and `export/draft-export`
compatibility aliases. No duplicate mutating implementation was found.

Provider-free baseline measurements:

| Command | Wall time | Peak RSS |
| --- | ---: | ---: |
| `creator-os --help` | 0.10 s | 25,018,368 bytes |
| `creator-os status --json` | 0.37 s | 58,654,720 bytes |
| `creator-os audio status --json` | 0.15 s | 37,388,288 bytes |
| `creator-os learning-refresh --dry-run` | 0.32 s | 72,318,976 bytes |
| `creator-os plan ... --dry-run` | 0.26 s | 49,283,072 bytes |
| `creator-os create ...` dry-run | 0.55 s | 67,305,472 bytes |
| `creator-os doctor` | 0.59 s | 63,455,232 bytes |

The CLI does not expose a distinct `doctor fast` tier; the canonical read-only
`doctor` command was measured instead. No benchmark threshold was changed.

## Documentation and schedules

The canonical system map remains `CREATOR_OS_SYSTEM_MAP.md`. Current operator
documentation now consistently uses the canonical healthy Stacey account
`bennett_s33`; historical fixtures were not rewritten. A single retention policy
was added under `docs/operations/`.

Nine Creator OS LaunchAgents were inspected. All are loaded, none points to a
removed worktree, and no duplicate label or missing executable target was found.
No schedule was unloaded, altered, or deleted. Audio refresh and offsite restore
drill have not yet recorded a completed run, but both target canonical paths and
were retained for operational review.

## Before and after

| Metric | Before | After automatic cleanup |
| --- | ---: | ---: |
| Logical bytes | 218,689,316,007 | 187,545,730,092 |
| File-block bytes | 223,121,379,328 | 189,124,542,464 |
| Files | 1,509,609 | 518,685 |
| Directories | 224,853 | 90,884 |
| Available disk | 523,542,142,976 | 526,974,365,696 |
| Worktrees | 16 | 4 after creating two active cleanup PR worktrees |
| Local branches | 15 | 3 including two active cleanup branches |

The source and runtime environments explain most remaining checkout weight.
Private models, libraries, historical runs, campaign artifacts, and backups
remain large because they are active, historically required, or not yet
reference-safe to prune.

## Cleanup workstreams

1. **Dead code and CLI simplification:** no PR opened; no proven safe deletion.
2. **Dependency/package weight:** draft PR only; reclassifies root `pytest` from
   production to development.
3. **Test/documentation/artifact hygiene:** draft PR only; fixes live account
   examples, adds this audit, and adds the retention policy.

Neither cleanup PR is merged. No release/security policy, provider selection,
runtime, schedule, publication, or production state changed.

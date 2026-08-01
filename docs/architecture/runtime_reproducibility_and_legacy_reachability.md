# Runtime Reproducibility And Legacy Reachability

Creator OS records exact inputs needed to compare two runtime environments, but
does not claim that host-native media output is byte-identical. macOS, Apple
Silicon versus Intel, FFmpeg builds, hardware encoders, fonts, Swift/Apple
Vision, and native framework behavior can change output bytes even when source
and configuration are equivalent.

## Equivalent-runtime manifest

`scripts/runtime_manifest.py` produces
`creator_os.equivalent_runtime_manifest.v1`. The canonical SBOM generator writes
it as `artifacts/sbom/toolchain-inventory.json` alongside the JavaScript and
Python CycloneDX documents.

The manifest fingerprints:

- the repository commit and dirty-state count;
- dependency manifests and the pnpm/uv lockfiles;
- resolved executable path, version, and SHA-256 for Node, pnpm, Python, uv,
  FFmpeg, FFprobe, and Tesseract;
- optional fpcalc, Swift, and strings availability and identity;
- Swift/Apple Vision integration-source bytes;
- Homebrew evidence for media/OCR formulae when Homebrew is available;
- every workflow file and every GitHub Action reference, including whether it
  is pinned to a full commit SHA;
- canonical and generated Pipeline Contract files;
- Reel Factory font bytes;
- provider/local model catalog identities and revisions;
- installed model bytes under the selected model root; and
- whether runtime/environment selectors and secret-bearing variables are set.

Environment variable values are never recorded. Secret values and hashes are
excluded. Missing required tools fail manifest generation; missing optional
tools are explicit. Symlinked or unreadable model entries make the model
inventory incomplete instead of being silently followed.

The qualification block is intentionally narrow:

```text
equivalentInputManifestComplete
does not imply
runtimeHealthProven
or
mediaOutputEquivalenceProven
```

A promoted runtime still needs its normal health checks and media qualification.

## Brace-expansion supported upgrade

Creator OS reaches `brace-expansion` through:

```text
eslint 10
→ minimatch 10
→ brace-expansion 5
```

This supported dependency chain avoids forcing an incompatible export into an
older minimatch release. `pnpm check:brace-expansion` verifies the installed
major version, its aggregate expansion-length bound, and brace matching through
minimatch's actual dependency path.

## Read-only legacy reachability

`scripts/legacy_reachability.py` parses repository Python without importing
application modules or opening runtime databases. It reports:

- static imports and literal dynamic imports;
- known package-script, operator-script, and `__main__` entrypoints;
- call names;
- modules reachable from those entrypoints;
- evidence-backed classifications for known compatibility surfaces; and
- the evidence still required before removal.

The allowed classifications are:

```text
active_required
active_reachable
compatibility_surface
experimental_research
historical_read_only_compatibility
migration_only
safe_to_migrate
safe_to_remove
unknown
```

Static unreachability is never converted into `safe_to_remove`. The report's
`safeToRemove` list remains empty until a separate evidence-backed change proves
all of the following:

```text
no repository caller
no dynamic or subprocess caller
no external operator workflow
no retained database row
no retained receipt or sidecar
migration and rollback exist
focused compatibility tests pass
```

Current classifications include:

| Surface | Classification | Reason |
|---|---|---|
| Creative Approval v1 | historical read-only compatibility | v1 remains non-operational audit evidence while v2 is active |
| ThreadsDashboard handshake v1 | active required | draft payload v2 still negotiates with it |
| generated-asset lineage v1 | active required | Reel Factory still produces v1 sidecars before Campaign upgrades lineage |
| provider-spend authorization v1 | active required | current Higgsfield execution authorization |
| retired Reel outcome tables | historical read-only compatibility | read-only migration/audit exporter |
| Reference paid-command shims | historical read-only compatibility | fail closed toward the governed root command |
| `sample-frames --videos` | compatibility surface | retained alias; external operator usage is unmeasured |
| `repurposer` | experimental research | isolated from production, but packaged and tested |
| local-model/Wan tooling | experimental research | outside public modes, but direct module tools and internal references remain |

No legacy code is deleted by this phase. Runtime databases, artifact roots,
external operator scripts, and ThreadsDashboard historical consumers must be
inventoried from a stable read-only snapshot before any removal proposal.
